import copy
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agents.adapters import BY_ID, failure
from agents.config import defaults, SettingsStore, validate_settings
from agents.runtime import AgentError, redact, resolve_launch
from agents.service import AgentService, ConflictError
from serve import make_server


class AgentFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent 设置 space ", dir=os.environ.get("CODE_ARCHITECTURE_TEST_TMP"))
        self.root = Path(self.temp.name)
        self.cli = self.root / "fake cli"
        self.cli.write_text(f"#!{sys.executable}\n" + (ROOT / "tests/fixtures/agent_cli.py").read_text())
        self.cli.chmod(0o700)
        self.config = {"executablePath": str(self.cli), "model": ""}
        self.service = AgentService(self.root / "settings.json", test_timeout=3)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.service.close)

    def wait(self, job):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = self.service.result(job["id"])
            if result["status"] != "running":
                return result
            time.sleep(.02)
        self.fail("fake connection test did not settle")

    def run_agent(self, agent_id="codex", mode="success", model=""):
        config = {**self.config, "model": model}
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_MODE": mode}):
            return self.wait(self.service.start_test({"agentId": agent_id, "config": config}))


class SettingsTests(AgentFixture):
    def test_roundtrip_and_no_probe_metadata_or_secrets(self):
        value = defaults()
        value["defaultAgentId"] = "codex"
        value["agents"]["codex"] = self.config
        self.service.store.save(value)
        self.assertEqual(SettingsStore(self.root / "settings.json").read()["settings"], value)
        self.assertEqual(stat.S_IMODE((self.root / "settings.json").stat().st_mode), 0o600)
        self.assertIsNone(self.service.store.read()["error"])
        with self.assertRaises(ValueError):
            self.service.store.save({**value, "apiKey": "forbidden"})

    def test_corrupt_config_is_visible_and_not_rewritten(self):
        path = self.root / "settings.json"
        path.write_text("{broken")
        result = self.service.store.read()
        self.assertTrue(result["error"])
        self.assertEqual(result["settings"], defaults())
        self.assertEqual(path.read_text(), "{broken")

    def test_save_failure_preserves_previous_file(self):
        original = defaults()
        self.service.store.save(original)
        changed = copy.deepcopy(original)
        changed["defaultAgentId"] = "pi"
        with patch("agents.config.os.replace", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.service.store.save(changed)
        self.assertEqual(self.service.store.read()["settings"], original)
        self.assertEqual(list(self.root.glob(".settings-*")), [])

    def test_validation_and_xdg_directory(self):
        for value in ({"version": 2}, {"version": 1, "agents": {"unknown": {}}},
                      {"version": 1, "agents": {"pi": {"model": "a\nb"}}},
                      {"version": 1, "agents": {"codex": {"executablePath": "relative"}}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_settings(value)
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)}):
            self.assertEqual(SettingsStore().path, self.root / "code-strata/settings.json")


class DetectionTests(AgentFixture):
    def test_absent_and_broken_agents_do_not_hide_other_results(self):
        with patch("agents.runtime.search_directories", return_value=[]):
            self.assertEqual(self.service._probe(BY_ID["pi"], {"executablePath": "", "model": ""})["status"], "not_found")
        configs = {key: dict(self.config) for key in BY_ID}
        configs["codex"]["executablePath"] += "-missing"
        value = defaults()
        value.update(agents=configs, defaultAgentId="codex")
        self.service.store.save(value)
        results = self.service.agents()["agents"]
        self.assertEqual(results[0]["status"], "unavailable")
        self.assertTrue(all(item["status"] == "detected" for item in results[1:]))
        self.assertEqual(self.service.store.read()["settings"]["defaultAgentId"], "codex")

    def test_spaces_symlinks_and_same_test_executable(self):
        link = self.root / "linked cli"
        link.symlink_to(self.cli)
        config = {"executablePath": str(link), "model": ""}
        detected = self.service._probe(BY_ID["codex"], config)
        self.assertEqual(detected["status"], "detected")
        self.assertIn("1.2.3", detected["version"])
        result = self.wait(self.service.start_test({"agentId": "codex", "config": config}))
        self.assertEqual(result["executablePath"], detected["executablePath"])
        self.assertEqual(result["status"], "success")

    def test_manual_bad_path_never_falls_back(self):
        config = {"executablePath": str(self.root / "missing"), "model": ""}
        result = self.service._probe(BY_ID["codex"], config)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["executablePath"])

    def test_missing_interpreter_and_failed_version_are_unavailable(self):
        broken = self.root / "broken"
        broken.write_text("#!/does/not/exist\n")
        broken.chmod(0o700)
        result = self.service._probe(BY_ID["codex"], {"executablePath": str(broken), "model": ""})
        self.assertEqual(result["status"], "unavailable")
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_MODE": "version_fail"}):
            self.assertEqual(self.service._probe(BY_ID["pi"], self.config)["status"], "unavailable")

    def test_cache_refresh_and_config_invalidation(self):
        configs = {key: dict(self.config) for key in BY_ID}
        with patch.object(self.service, "_probe", wraps=self.service._probe) as probe:
            self.assertEqual(len(self.service.agents(configs=configs)["agents"]), 5)
            self.service.agents(configs=configs)
            self.assertEqual(probe.call_count, 5)
            self.service.agents(force=True, configs=configs)
            self.assertEqual(probe.call_count, 10)
            configs["pi"]["executablePath"] += "-missing"
            self.service.agents(configs=configs)
            self.assertEqual(probe.call_count, 15)

    def test_node_shebang_uses_explicit_node_and_consistent_path(self):
        wrapper = self.root / "node agent"
        wrapper.write_text("#!/usr/bin/env node\nconsole.log('version');\n")
        wrapper.chmod(0o700)
        with patch("agents.runtime.resolve_node", return_value={"status": "ready", "executable": "/valid/node"}):
            launch = resolve_launch(BY_ID["pi"], {"executablePath": str(wrapper), "model": ""}, "/valid/node")
        self.assertEqual(launch["command"], ["/valid/node", str(wrapper.resolve())])
        self.assertEqual(launch["env"]["PATH"].split(os.pathsep)[0], "/valid")


class ConnectionTests(AgentFixture):
    def test_error_categories_and_environment_secrets(self):
        self.assertEqual(failure("not authenticated").kind, "auth")
        self.assertEqual(failure("Model 'unknown' does not exist").kind, "model")
        with patch.dict(os.environ, {"SAMPLE_API_KEY": "private_value_without_prefix"}):
            self.assertNotIn("private_value_without_prefix", redact("failure: private_value_without_prefix"))

    def test_all_five_adapters_and_model_overrides(self):
        trace = self.root / "trace.jsonl"
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_TRACE": str(trace)}):
            for key in BY_ID:
                with self.subTest(agent=key):
                    result = self.run_agent(key, model="provider/model")
                    self.assertEqual(result["status"], "success", result)
                    self.assertEqual(result["response"], "CODESTRATA_OK")
        records = [json.loads(line) for line in trace.read_text().splitlines()]
        for record in records:
            if "cwd" in record:
                self.assertNotEqual(record["cwd"], str(ROOT))
                self.assertFalse(Path(record["cwd"]).exists())
            args = record.get("args", [])
            if args and args[0] != "--profile":
                self.assertIn("--model", args)
                self.assertIn("provider/model", args)
        methods = [record.get("method") for record in records]
        self.assertIn("session/set_config_option", methods)
        self.assertIn("session/close", methods)

    def test_default_model_is_not_overridden(self):
        trace = self.root / "trace.jsonl"
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_TRACE": str(trace)}):
            self.assertEqual(self.run_agent()["status"], "success")
        records = [json.loads(line) for line in trace.read_text().splitlines()]
        self.assertNotIn("--model", records[0]["args"])
        self.assertIn("Do not use tools", records[1]["prompt"])

    def test_exit_zero_is_insufficient_and_auth_errors_are_redacted(self):
        for key in ("codex", "opencode", "claude", "pi", "dsh"):
            with self.subTest(agent=key):
                result = self.run_agent(key, mode="auth")
                self.assertEqual(result["status"], "failed", result)
                self.assertEqual(result["kind"], "auth", result)
                self.assertNotIn("sk-secret-test-value", json.dumps(result))
                self.assertNotIn("sensitive-token", json.dumps(result))

    def test_empty_wrong_malformed_and_incomplete_outputs_fail(self):
        for mode in ("empty", "wrong", "malformed", "incomplete", "protocol_error", "overflow"):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_agent(mode=mode)["status"], "failed")

    def test_dsh_unknown_model_is_rejected_and_session_closed(self):
        trace = self.root / "trace.jsonl"
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_TRACE": str(trace)}):
            result = self.run_agent("dsh", model="unknown/model")
        self.assertEqual(result["kind"], "model")
        self.assertIn("session/close", trace.read_text())

    def test_dsh_permission_requests_are_not_approved(self):
        trace = self.root / "trace.jsonl"
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_TRACE": str(trace)}):
            self.assertEqual(self.run_agent("dsh", mode="permission")["status"], "success")
        self.assertIn('"outcome": "cancelled"', trace.read_text())

    def test_single_flight_cancel_and_timeout(self):
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_MODE": "hang"}):
            first = self.service.start_test({"agentId": "codex", "config": self.config})
            with self.assertRaises(ConflictError):
                self.service.start_test({"agentId": "pi", "config": self.config})
            self.service.cancel(first["id"])
            self.assertEqual(self.wait(first)["status"], "cancelled")
            self.service.test_timeout = .15
            second = self.service.start_test({"agentId": "pi", "config": self.config})
            self.assertEqual(self.wait(second)["kind"], "timeout")

    def test_service_close_cancels_dsh_and_sends_protocol_cleanup(self):
        trace = self.root / "trace.jsonl"
        with patch.dict(os.environ, {"CODE_STRATA_FAKE_MODE": "hang", "CODE_STRATA_FAKE_TRACE": str(trace)}):
            job = self.service.start_test({"agentId": "dsh", "config": self.config})
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and (not trace.exists() or "session/prompt" not in trace.read_text()):
                time.sleep(.02)
            self.service.close()
        self.assertEqual(self.service.result(job["id"])["status"], "cancelled")
        self.assertIn("session/cancel", trace.read_text())
        self.assertIn("session/close", trace.read_text())


class AgentApiTests(AgentFixture):
    def setUp(self):
        super().setUp()
        self.server = make_server(settings_path=self.root / "http-settings.json", agent_test_timeout=2)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        with urlopen(self.base) as response:
            self.token = re.search('architecture-token" content="([^"]+)', response.read().decode())[1]
        self.addCleanup(self.cleanup_server)

    def cleanup_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def request(self, route, body=None, token=None, origin=None):
        headers = {"X-Architecture-Token": token or self.token}
        if origin:
            headers["Origin"] = origin
        if body is not None:
            headers["Content-Type"] = "application/json"
        with urlopen(Request(self.base + route, data=None if body is None else json.dumps(body).encode(), headers=headers), timeout=5) as response:
            return response.status, json.load(response)

    def test_http_config_detection_and_draft_test(self):
        self.assertIsNone(self.request("/api/settings")[1]["settings"]["defaultAgentId"])
        settings = defaults()
        settings["agents"] = {key: dict(self.config) for key in BY_ID}
        settings["defaultAgentId"] = "pi"
        self.request("/api/settings", settings)
        detected = self.request("/api/agents/detect", {"agents": settings["agents"]})[1]
        self.assertTrue(all(item["status"] == "detected" for item in detected["agents"]))
        code, job = self.request("/api/agents/tests", {"agentId": "codex", "config": self.config})
        self.assertEqual(code, 202)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            result = self.request(f'/api/agents/tests/{job["id"]}')[1]
            if result["status"] != "running":
                break
            time.sleep(.02)
        self.assertEqual(result["status"], "success")
        self.assertEqual(self.request("/api/settings")[1]["settings"]["defaultAgentId"], "pi")

    def test_untrusted_sources_cannot_read_save_or_spawn(self):
        for route, body in (("/api/settings", None), ("/api/settings", defaults()),
                            ("/api/agents/tests", {"agentId": "codex", "config": self.config})):
            for options in ({"token": "wrong"}, {"origin": "https://evil.example"}):
                with self.subTest(route=route, options=options), self.assertRaises(HTTPError) as error:
                    self.request(route, body, **options)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
        self.assertFalse((self.root / "http-settings.json").exists())
        self.assertEqual(self.server.agents.tests, {})

    @unittest.skipIf(os.name == "nt", "POSIX SIGTERM lifecycle")
    def test_cli_sigterm_cleans_up_running_test(self):
        trace = self.root / "shutdown-trace.jsonl"
        env = {**os.environ, "CODE_STRATA_FAKE_MODE": "hang", "CODE_STRATA_FAKE_TRACE": str(trace),
               "XDG_CONFIG_HOME": str(self.root / "user-config")}
        child = subprocess.Popen([sys.executable, "-u", str(ROOT / "scripts/serve.py"), "--port", "0"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            info = json.loads(child.stdout.readline())
            with urlopen(info["url"]) as response:
                token = re.search('architecture-token" content="([^"]+)', response.read().decode())[1]
            body = json.dumps({"agentId": "pi", "config": self.config}).encode()
            with urlopen(Request(info["url"] + "/api/agents/tests", data=body,
                headers={"X-Architecture-Token": token, "Content-Type": "application/json"})) as response:
                self.assertEqual(response.status, 202)
            deadline = time.monotonic() + 3
            while not trace.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            pid = json.loads(trace.read_text().splitlines()[0])["pid"]
            child.terminate()
            child.communicate(timeout=6)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
