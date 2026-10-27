import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from directory_picker import choose_directory, DirectoryPickerUnavailable
from serve import make_server


class DirectoryPickerTests(unittest.TestCase):
    def test_selection_preserves_unicode_spaces_and_literal_arguments(self):
        with tempfile.TemporaryDirectory(prefix='项目 " $(literal) ') as directory:
            with patch("directory_picker.sys.platform", "darwin"), patch(
                "directory_picker.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, directory + "/\n", ""),
            ) as run:
                self.assertEqual(choose_directory(directory), directory)
                self.assertEqual(run.call_args.args[0][-1], directory)
                self.assertNotIn(directory, run.call_args.args[0][2])
                self.assertNotIn("shell", run.call_args.kwargs)

    def test_cancel_and_unavailable_are_distinct(self):
        with patch("directory_picker.subprocess.run") as run:
            run.return_value.stdout = "\n"
            self.assertIsNone(choose_directory())
            for error in (OSError(), subprocess.TimeoutExpired("picker", 120)):
                run.side_effect = error
                with self.assertRaises(DirectoryPickerUnavailable):
                    choose_directory()

    def test_invalid_result_is_rejected(self):
        with patch("directory_picker.subprocess.run") as run:
            run.return_value.stdout = "relative/path\n"
            with self.assertRaises(DirectoryPickerUnavailable):
                choose_directory()
        with self.assertRaises(ValueError):
            choose_directory(["invalid"])

    def test_non_mac_picker_runs_in_child_main_thread(self):
        with patch("directory_picker.sys.platform", "linux"), patch(
            "directory_picker.subprocess.run"
        ) as run:
            run.return_value.stdout = "\n"
            self.assertIsNone(choose_directory())
            self.assertEqual(run.call_args.args[0][:2], [sys.executable, "-c"])


class DirectoryPickerApiTests(unittest.TestCase):
    def setUp(self):
        self.server = make_server()
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        with urlopen(self.base) as response:
            html = response.read().decode()
        self.token = re.search('architecture-token" content="([^"]+)', html).group(1)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def request(self, body=None, token=None, origin=None, route="/api/select-directory"):
        headers = {"Content-Type": "application/json", "X-Architecture-Token": token or self.token}
        if origin:
            headers["Origin"] = origin
        with urlopen(Request(self.base + route, data=json.dumps(body or {}).encode(), headers=headers), timeout=10) as response:
            return json.load(response)

    def test_selection_cancel_failure_and_auth_do_not_change_project(self):
        with patch("serve.choose_directory", return_value="/selected/项目") as picker:
            self.assertEqual(self.request({"path": "/initial"}), {"path": "/selected/项目"})
            picker.assert_called_once_with("/initial")
            picker.reset_mock()
            for options in ({"token": "invalid"}, {"origin": "https://external.example"}):
                with self.assertRaises(HTTPError) as error:
                    self.request(**options)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            picker.assert_not_called()
            picker.return_value = None
            self.assertEqual(self.request(), {"path": None})
            picker.side_effect = DirectoryPickerUnavailable("请手动输入路径")
            with self.assertRaises(HTTPError) as error:
                self.request()
            self.assertEqual(error.exception.code, 503)
            error.exception.close()
            picker.side_effect = None
            self.assertEqual(self.request(), {"path": None})
        with urlopen(Request(self.base + "/api/project", headers={"X-Architecture-Token": self.token})) as response:
            self.assertEqual(json.load(response), {"demo": True})

    def test_only_one_picker_opens_at_a_time(self):
        entered, release = threading.Event(), threading.Event()
        results = []

        def pick(_):
            entered.set()
            release.wait(5)
            return None

        with patch("serve.choose_directory", side_effect=pick):
            first = threading.Thread(target=lambda: results.append(self.request()))
            first.start()
            try:
                self.assertTrue(entered.wait(3))
                with self.assertRaises(HTTPError) as error:
                    self.request()
                self.assertEqual(error.exception.code, 409)
                error.exception.close()
            finally:
                release.set()
                first.join(5)
            self.assertEqual(results, [{"path": None}])


if __name__ == "__main__":
    unittest.main()
