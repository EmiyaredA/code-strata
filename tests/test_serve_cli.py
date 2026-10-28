import contextlib
import errno
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from serve import main


class ServeCliTests(unittest.TestCase):
    def launch(self, args, expected_port, actual_port):
        server = Mock(server_port=actual_port)
        server.serve_forever.side_effect = KeyboardInterrupt
        output = io.StringIO()
        with patch("serve.make_server", return_value=server) as create, \
                contextlib.redirect_stdout(output):
            main(args)
        self.assertEqual(create.call_args.args[3], expected_port)
        self.assertEqual(json.loads(output.getvalue())["url"],
                         f"http://127.0.0.1:{actual_port}")
        server.server_close.assert_called_once_with()

    def test_default_cli_port_is_fixed(self):
        self.launch([], 8765, 8765)

    def test_explicit_and_automatic_ports_remain_available(self):
        self.launch(["--port", "9000"], 9000, 9000)
        self.launch(["--port", "0"], 0, 54365)

    def test_occupied_port_reports_remedy_without_retry(self):
        error = OSError(errno.EADDRINUSE, "Address already in use")
        stderr = io.StringIO()
        with patch("serve.make_server", side_effect=error) as create, \
                contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as result:
                main([])
        self.assertEqual(result.exception.code, 1)
        create.assert_called_once()
        self.assertIn("端口 8765 已被占用", stderr.getvalue())
        self.assertIn("--port 0", stderr.getvalue())

    def test_invalid_port_fails_before_server_creation(self):
        for value in ("-1", "65536", "abc"):
            with self.subTest(value=value), patch("serve.make_server") as create, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    main(["--port", value])
                self.assertEqual(result.exception.code, 2)
                create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
