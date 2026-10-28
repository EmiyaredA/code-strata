from concurrent.futures import ThreadPoolExecutor
import copy
import http.client
import json
import os
from pathlib import Path
import re
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_agents import AgentFixture
from agents.adapters import BY_ID
from agents.models import codex_models, opencode_models, pi_models, acp_models
from agents.runtime import AgentError, Process
from serve import make_server


class CatalogParserTests(unittest.TestCase):
    def test_codex_filters_hidden_deduplicates_and_discards_prompts(self):
        value = {"models": [{"slug": "m1", "display_name": "Model One", "base_instructions": "secret"},
                            {"slug": "m1"}, {"slug": "m2"}, {"slug": "hidden", "visibility": "hidden"}]}
        self.assertEqual(codex_models(json.dumps(value)), [{"id": "m1", "label": "Model One"}, {"id": "m2", "label": "m2"}])

    def test_opencode_verbose_and_plain_catalogs(self):
        value = 'p/m\n{\n "name": "Friendly", "details": {"a": 1}\n}\np/second\np/m\n'
        self.assertEqual(opencode_models(value), [{"id": "p/m", "label": "Friendly", "provider": "p"},
                                                {"id": "p/second", "label": "p/second", "provider": "p"}])
        self.assertEqual(len(opencode_models("p/m\np/n")), 2)
        with self.assertRaises(AgentError):
            opencode_models("p/m\n{broken")

    def test_pi_ansi_empty_and_variable_column_width(self):
        value = "provider model context\n\x1b[32mp    m\x1b[0m   1000\np m 1000\nq long-id 2000"
        self.assertEqual([row["id"] for row in pi_models(value)], ["p/m", "q/long-id"])
        self.assertEqual(pi_models("provider model context"), [])

    def test_acp_groups_preserve_opaque_ids_and_legacy_models(self):
        value = {"configOptions": [{"id": "model", "options": [{"name": "Provider", "options": [
            {"value": "opaque-id", "name": "Readable"}, {"value": "opaque-id"}, {"value": "other"}]}]}]}
        self.assertEqual(acp_models(value), [{"id": "opaque-id", "label": "Readable", "provider": "Provider"},
                                             {"id": "other", "label": "other", "provider": "Provider"}])
        self.assertEqual(acp_models({"models": {"availableModels": [{"modelId": "old-id", "name": "Old"}]}})[0]["id"], "old-id")


class CatalogTests(AgentFixture):
    def catalog(self, agent_id="codex", mode="success", force=False, model=""):
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_MODE": mode}):
            return self.service.model_catalog.get({"agentId": agent_id, "config": {**self.config, "model": model}, "force": force})

    def test_five_native_catalogs_never_send_generation_messages(self):
        trace = self.root / "models-trace.jsonl"
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_TRACE": str(trace)}):
            for agent_id in BY_ID:
                with self.subTest(agent=agent_id):
                    result = self.catalog(agent_id)
                    self.assertEqual(result["status"], "ready", result)
                    self.assertTrue(result["models"])
                    self.assertTrue(result["fetchedAt"])
                    self.assertNotIn("base_instructions", json.dumps(result))
                    self.assertNotIn("do not expose", json.dumps(result))
        records = [json.loads(line) for line in trace.read_text().splitlines()]
        self.assertTrue(all("prompt" not in record for record in records))
        self.assertNotIn("session/prompt", [record.get("method") for record in records])
        self.assertIn("session/close", [record.get("method") for record in records])
        self.assertTrue(all(record.get("type") != "user" for record in records))
        for record in records:
            if "cwd" in record:
                self.assertFalse(Path(record["cwd"]).exists())

    def test_empty_unsupported_malformed_and_grouped_results(self):
        for agent_id in BY_ID:
            with self.subTest(agent=agent_id):
                self.assertEqual(self.catalog(agent_id, "models_empty", force=True)["status"], "empty")
        for agent_id in ("codex", "opencode", "claude", "dsh"):
            with self.subTest(unsupported=agent_id):
                self.assertEqual(self.catalog(agent_id, "models_unsupported", force=True)["status"], "unsupported")
        self.assertEqual(self.catalog("codex", "models_malformed", force=True)["kind"], "protocol")
        self.assertEqual(self.catalog("dsh", "models_grouped", force=True)["models"][0]["id"], "opaque:id:1")
        self.assertEqual(self.catalog("dsh", "models_logs", force=True)["status"], "ready")

    def test_cache_ignores_model_override_and_force_refreshes(self):
        with patch.object(self.service.model_catalog, "_query", wraps=self.service.model_catalog._query) as query:
            first = self.catalog()
            second = self.catalog(model="other-model")
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            self.assertEqual(query.call_count, 1)
            self.catalog(force=True)
            self.assertEqual(query.call_count, 2)
            key = next(iter(self.service.model_catalog.cache))
            stamp, value = self.service.model_catalog.cache[key]
            self.service.model_catalog.cache[key] = stamp - 301, value
            self.catalog()
            self.assertEqual(query.call_count, 3)
            self.cli.touch()
            self.catalog()
            self.assertEqual(query.call_count, 4)

    def test_concurrent_same_configuration_is_single_flight(self):
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_MODE": "models_slow"}), \
                patch.object(self.service.model_catalog, "_query", wraps=self.service.model_catalog._query) as query:
            body = {"agentId": "codex", "config": self.config, "force": True}
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: self.service.model_catalog.get(body), range(4)))
            self.assertTrue(all(result["status"] == "ready" for result in results))
            self.assertEqual(query.call_count, 1)

    def test_only_two_queries_run_at_once(self):
        counter = {"current": 0, "peak": 0}
        lock = threading.Lock()
        class CountedProcess(Process):
            def __init__(inner, *args, **kwargs):
                super().__init__(*args, **kwargs)
                with lock:
                    counter["current"] += 1
                    counter["peak"] = max(counter["peak"], counter["current"])
            def close(inner):
                try:
                    super().close()
                finally:
                    with lock:
                        counter["current"] -= 1
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_MODE": "models_slow"}), patch("agents.model_catalog.Process", CountedProcess):
            with ThreadPoolExecutor(max_workers=5) as pool:
                results = list(pool.map(lambda agent: self.service.model_catalog.get({"agentId": agent, "config": self.config}), BY_ID))
        self.assertTrue(all(result["status"] == "ready" for result in results))
        self.assertLessEqual(counter["peak"], 2)
        self.assertEqual(counter["current"], 0)

    def test_timeout_shutdown_and_large_bounded_output(self):
        self.service.model_catalog.timeout = .15
        self.assertEqual(self.catalog(mode="models_hang")["kind"], "timeout")
        self.service.model_catalog.timeout = 3
        result = self.catalog(mode="models_big", force=True)
        self.assertEqual(result["status"], "ready", result)
        self.assertLess(len(json.dumps(result)), 2000)
        self.assertEqual(self.catalog(mode="models_overflow", force=True)["kind"], "protocol")
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_MODE": "models_hang"}):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.service.model_catalog.get, {"agentId": "pi", "config": self.config})
                time.sleep(.08)
                self.service.close()
                self.assertEqual(future.result(timeout=3)["kind"], "cancelled")

    def test_manual_bad_path_and_validation(self):
        bad = {**self.config, "executablePath": str(self.root / "missing")}
        result = self.service.model_catalog.get({"agentId": "codex", "config": bad})
        self.assertEqual(result["status"], "unavailable")
        for body in ({"agentId": "unknown"}, {"agentId": "codex", "force": "yes"}, {"agentId": "codex", "token": "secret"}):
            with self.assertRaises(ValueError):
                self.service.model_catalog.get(body)

    def test_http_authentication_and_unsaved_configuration(self):
        server = make_server(settings_path=self.root / "models-settings.json")
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base) as response:
                token = re.search('architecture-token" content="([^"]+)', response.read().decode())[1]
            body = json.dumps({"agentId": "codex", "config": self.config}).encode()
            for headers in ({"X-Architecture-Token": "wrong"}, {"X-Architecture-Token": token, "Origin": "https://evil.example"}):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/api/agents/models", data=body, headers={**headers, "Content-Type": "application/json"}))
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            try:
                connection.request("POST", "/api/agents/models", body=body,
                    headers={"Host": "evil.example", "X-Architecture-Token": token, "Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
            finally:
                connection.close()
            with urlopen(Request(base + "/api/agents/models", data=body,
                headers={"X-Architecture-Token": token, "Content-Type": "application/json"})) as response:
                result = json.load(response)
                self.assertEqual(result["status"], "ready")
                self.assertNotIn("details", result)
            self.assertFalse((self.root / "models-settings.json").exists())
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
