import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from counting import find_scc
from inventory import classify, verify_inputs
from scan import scan_project

NODE = os.environ.get("CODE_ARCHITECTURE_TEST_NODE")


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("CODE_ARCHITECTURE_TEST_TMP"))
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def scan(self, **options):
        return scan_project(self.root, node=NODE, **options)

    def test_real_scc_counts_categories_and_unsupported_parser(self):
        self.assertIsNotNone(find_scc(), "This acceptance test requires the prepared scc counter")
        self.write("src/a.py", "# comment\n\nvalue = 1\n")
        self.write("src/main.go", "package main\n")
        self.write("tests/test_a.py", "value = 2\n")
        self.write("src/generated/types.ts", "// @generated\nexport const x = 1;\n")
        self.write("vendor/lib.py", "value = 3\n")
        before = {
            p.relative_to(self.root).as_posix(): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file()
        }
        data = self.scan()
        self.assertEqual(data["metrics"]["tool"]["status"], "ready")
        self.assertEqual(data["metrics"]["categories"]["source"]["code"], 2)
        self.assertEqual(data["metrics"]["categories"]["source"]["comments"], 1)
        self.assertEqual(data["metrics"]["categories"]["source"]["blanks"], 1)
        for category in ("test", "generated", "third-party"):
            self.assertEqual(data["metrics"]["categories"][category]["code"], 1)
        go = next(x for x in data["inventory"] if x["id"] == "src/main.go")
        self.assertEqual((go["parseStatus"], go["countStatus"]), ("unsupported", "counted"))
        self.assertEqual(
            before,
            {
                p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob("*")
                if p.is_file()
            },
        )

    def test_missing_counter_and_invalid_source_are_not_zero(self):
        self.write("broken.py", "def invalid(")
        self.write("other.go", "package main\n")
        data = self.scan(scc="/not/a/counter")
        self.assertIsNone(data["metrics"]["total"]["code"])
        self.assertEqual(data["coverage"]["parsing"]["failed"], 1)
        self.assertEqual(data["coverage"]["parsing"]["unsupported"], 1)
        self.assertEqual(data["coverage"]["counting"]["counted"], 0)
        self.assertTrue(any("未采集" in d["message"] for d in data["diagnostics"]))

    def test_parser_budget_does_not_remove_counted_file(self):
        self.write("large.py", "# comment\n" * 60000)
        data = self.scan()
        item = data["inventory"][0]
        self.assertEqual(item["countStatus"], "counted")
        self.assertEqual(item["parseStatus"], "skipped")
        self.assertEqual(item["metrics"]["comments"], 60000)
        self.assertEqual(data["coverage"]["parsing"]["total"], 1)

    def test_shared_members_count_once_and_real_reference_units(self):
        self.write("src/save.py", "from shared import x\n")
        self.write("src/shared.py", "x = 1\n")
        mapping = self.write(
            "map.json",
            json.dumps(
                {
                    "version": 1,
                    "groups": [
                        {
                            "id": "save",
                            "title": "Save",
                            "files": ["src/save.py", "src/shared.py", "src/shared.py"],
                        },
                        {"id": "shared", "title": "Shared", "files": ["src/shared.py"]},
                    ],
                }
            ),
        )
        data = self.scan(mapping_path=mapping)
        self.assertEqual(data["metrics"]["total"]["files"], 2)
        self.assertEqual(data["groups"][0]["stats"]["total"]["files"], 2)
        self.assertEqual(data["groups"][0]["stats"]["outgoing"], 0)
        self.assertEqual(data["groups"][1]["stats"]["incoming"], 1)

    def test_npm_workspace_versions_declarations_and_usage_are_separate(self):
        self.write(
            "package.json", json.dumps({"dependencies": {"react": "^18.0.0", "vue": "^3.0.0"}})
        )
        self.write("apps/editor/package.json", json.dumps({"dependencies": {"react": "^19.0.0"}}))
        self.write("apps/editor/main.tsx", 'import React from "react"; export const x = 1;')
        lock = self.write(
            "package-lock.json",
            json.dumps(
                {
                    "lockfileVersion": 3,
                    "packages": {
                        "node_modules/react": {"version": "18.3.1"},
                        "apps/editor/node_modules/react": {"version": "19.1.1"},
                        "node_modules/vue": {"version": "3.5.0"},
                    },
                }
            ),
        )
        data = self.scan()
        react = next(x for x in data["technologies"] if x["name"] == "React")
        self.assertEqual(
            {(x["scope"], x["value"]) for x in react["locked"]},
            {(".", "18.3.1"), ("apps/editor", "19.1.1")},
        )
        self.assertEqual(len(react["references"]), 1)
        vue = next(x for x in data["technologies"] if x["name"] == "Vue")
        self.assertEqual(vue["references"], [])
        self.assertEqual(vue["runtimeStatus"], "not-observed")
        initial = data["snapshot"]["analysisInputHash"]
        lock.write_text(lock.read_text().replace("19.1.1", "19.1.2"))
        self.assertNotEqual(initial, self.scan()["snapshot"]["analysisInputHash"])

    def test_python_uv_multiple_versions_and_missing_lock(self):
        self.write(
            "pyproject.toml",
            '[project]\nrequires-python = ">=3.11"\n'
            'dependencies = ["fastapi>=0.110", "sqlalchemy>=2"]\n',
        )
        self.write("main.py", "from fastapi import FastAPI\n")
        data = self.scan()
        fastapi = next(x for x in data["technologies"] if x["name"] == "FastAPI")
        self.assertEqual(fastapi["locked"], [])
        self.assertEqual(len(fastapi["references"]), 1)
        self.write(
            "uv.lock",
            'version = 1\n[[package]]\nname = "fastapi"\nversion = "0.110.0"\n'
            '[[package]]\nname = "fastapi"\nversion = "0.111.0"\n',
        )
        fastapi = next(x for x in self.scan()["technologies"] if x["name"] == "FastAPI")
        self.assertEqual({x["value"] for x in fastapi["locked"]}, {"0.110.0", "0.111.0"})
        self.assertTrue(all(x["kind"] == "locked-candidate" for x in fastapi["locked"]))
        self.assertEqual({x["line"] for x in fastapi["locked"]}, {4, 7})

    def test_invalid_config_and_internal_shadow_do_not_invent_stack(self):
        self.write("package.json", "{bad json")
        self.write("fastapi.py", "class FastAPI: pass\n")
        self.write("main.py", "from fastapi import FastAPI\n")
        data = self.scan()
        self.assertNotIn("FastAPI", [x["name"] for x in data["technologies"]])
        self.assertTrue(any(d["kind"] == "technology" for d in data["diagnostics"]))

    def test_capture_budget_and_missing_parser_are_explicit(self):
        self.write("main.ts", "export const x = 1;")
        with patch("inventory.MAX_FILE_SIZE", 4):
            data = self.scan()
        self.assertEqual(data["inventory"][0]["captureStatus"], "skipped")
        self.assertEqual(data["metrics"]["total"]["countedFiles"], 0)
        self.assertEqual(data["metrics"]["total"]["status"], "partial")
        data = scan_project(self.root, node="/not/node")
        self.assertEqual(data["inventory"][0]["countStatus"], "counted")
        self.assertEqual(data["coverage"]["parsing"]["unavailable"], 1)

    def test_changed_source_discards_related_conclusions(self):
        path = self.write("main.py", "import sqlite3\n")

        def mutate(root, entries, originals):
            path.write_text("value = 2\n")
            return verify_inputs(root, entries, originals)

        with patch("scan.verify_inputs", side_effect=mutate):
            data = self.scan()
        self.assertEqual(data["files"], [])
        self.assertEqual(data["inventory"][0]["captureStatus"], "changed")
        self.assertIsNone(data["inventory"][0]["metrics"])
        self.assertNotIn("SQLite", [x["name"] for x in data["technologies"]])

    def test_vendor_dependencies_do_not_pollute_project_stack(self):
        self.write("src/main.py", "value = 1\n")
        self.write("vendor/sample/pyproject.toml", '[project]\ndependencies = ["fastapi>=0.1"]\n')
        self.write("vendor/sample/main.py", "import fastapi\n")
        self.assertNotIn("FastAPI", [t["name"] for t in self.scan()["technologies"]])

    def test_invalid_nearest_lock_does_not_borrow_parent_version(self):
        self.write(
            "package-lock.json",
            json.dumps(
                {"lockfileVersion": 3, "packages": {"node_modules/react": {"version": "18.3.1"}}}
            ),
        )
        self.write("apps/editor/package.json", json.dumps({"dependencies": {"react": "^19"}}))
        self.write("apps/editor/package-lock.json", "{invalid")
        self.write("apps/editor/main.ts", "export const x = 1;")
        tech = next(t for t in self.scan()["technologies"] if t["name"] == "React")
        self.assertEqual(tech["locked"], [])

    def test_classification_is_deterministic_and_explained(self):
        self.assertEqual(classify("vendor/tests/a.py", "# @generated")[0], "third-party")
        self.assertEqual(classify("tests/generated/a.ts", "")[0], "generated")
        self.assertEqual(classify("src/a.spec.ts", "")[0], "test")
        self.assertEqual(classify("src/a.ts", "")[0], "source")
        self.assertTrue(classify("src/a.ts", "")[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
