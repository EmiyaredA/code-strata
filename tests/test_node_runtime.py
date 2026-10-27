from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from node_runtime import resolve_node
from scan import scan_project


class NodeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.name = "node.exe" if os.name == "nt" else "node"
        self.bins = [self.root / "first", self.root / "second"]
        for directory in self.bins:
            directory.mkdir()
            (directory / self.name).touch()

    def test_broken_first_path_candidate_does_not_disable_all_js_files(self):
        def version(command, **_):
            if command[0] == str((self.bins[0] / self.name).resolve()):
                raise subprocess.CalledProcessError(-6, command)
            return subprocess.CompletedProcess(command, 0, "v26.12.1\n", "")
        with patch("node_runtime.os.get_exec_path", return_value=[str(p) for p in self.bins]), patch("node_runtime.subprocess.run", side_effect=version):
            runtime = resolve_node()
        self.assertEqual(runtime["status"], "ready")
        self.assertEqual(runtime["executable"], str((self.bins[1] / self.name).resolve()))

    def test_explicit_broken_runtime_is_not_silently_replaced(self):
        with patch("node_runtime.subprocess.run", side_effect=OSError):
            runtime = resolve_node(str(self.bins[0] / self.name))
        self.assertEqual(runtime["status"], "unavailable")
        self.assertIsNone(runtime["executable"])
        self.assertIn("--node", runtime["message"])

    def test_old_version_is_skipped_and_newer_version_is_used(self):
        with patch("node_runtime.os.get_exec_path", return_value=[str(p) for p in self.bins]), patch("node_runtime.subprocess.run", side_effect=[
            subprocess.CompletedProcess([], 0, "v16.20.2\n", ""),
            subprocess.CompletedProcess([], 0, "v18.20.0\n", ""),
        ]):
            self.assertEqual(resolve_node()["version"], "v18.20.0")

    def test_timeout_and_invalid_version_are_explicitly_unavailable(self):
        with patch("node_runtime.os.get_exec_path", return_value=[str(p) for p in self.bins]), patch("node_runtime.subprocess.run", side_effect=[
            subprocess.TimeoutExpired("node", 5),
            subprocess.CompletedProcess([], 0, "not node", ""),
        ]):
            self.assertEqual(resolve_node()["status"], "unavailable")

    def test_same_executable_is_not_probed_twice(self):
        with patch("node_runtime.os.get_exec_path", return_value=[str(self.bins[0])] * 2), patch("node_runtime.subprocess.run", side_effect=OSError) as run:
            resolve_node()
            self.assertEqual(run.call_count, 1)

    def test_runtime_recovery_changes_snapshot_and_preserves_failure_reason(self):
        node = os.environ.get("CODE_ARCHITECTURE_TEST_NODE")
        if not node:
            node = resolve_node()["executable"]
        if not node:
            self.skipTest("Requires a working Node.js runtime")
        project = self.root / "project"
        project.mkdir()
        (project / "main.ts").write_text('import { value } from "./shared";')
        (project / "shared.ts").write_text("export const value = 1;")
        unavailable = scan_project(project, node="/not/a/node")
        ready = scan_project(project, node=node)
        self.assertEqual(unavailable["coverage"]["parsing"]["unavailable"], 2)
        self.assertIn("--node", unavailable["inventory"][0]["parseReason"])
        self.assertEqual(ready["coverage"]["parsing"]["parsed"], 2)
        self.assertEqual(len(ready["imports"]), 1)
        self.assertNotEqual(unavailable["snapshot"]["id"], ready["snapshot"]["id"])


if __name__ == "__main__":
    unittest.main()
