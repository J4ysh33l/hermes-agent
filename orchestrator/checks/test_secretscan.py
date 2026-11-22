"""Behaviour of secretscan: real-looking credentials fail, placeholders and allowed lines pass.

Fake credentials are assembled at run time so this file never matches its own rules.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import secretscan

FAKES = {
    "telegram bot token": "123456789:" + "AA" + "x" * 33,
    "google api key": "AI" + "za" + "B" * 35,
    "slack token": "xo" + "xb-" + "1234567890-abcdefghij",
    "aws access key": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "private key block": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "github token": "gh" + "p_" + "a" * 36,
}


class ScanText(unittest.TestCase):
    def test_each_credential_shape_is_caught(self):
        for rule, value in FAKES.items():
            with self.subTest(rule=rule):
                rules = {f.rule for f in secretscan.scan_text("f.py", f"x = '{value}'\n")}
                self.assertIn(rule, rules)

    def test_placeholders_and_env_lookups_pass(self):
        clean = (
            'TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]\n'
            "api_key: /PATH/TO/your-key-goes-here-in-dotenv\n"
            "token = get_token()\n"
        )
        self.assertEqual(secretscan.scan_text("f.py", clean), [])

    def test_allow_mark_skips_a_line(self):
        line = f"x = '{FAKES['google api key']}'  # secretscan: allow -- documented sample\n"
        self.assertEqual(secretscan.scan_text("f.py", line), [])

    def test_reports_line_numbers(self):
        text = "ok\n" + f"k = '{FAKES['slack token']}'\n"
        self.assertEqual([f.line for f in secretscan.scan_text("f.py", text)], [2])


class ScanPath(unittest.TestCase):
    def test_credential_file_names_are_refused(self):
        for name in (".env", "config/.env.prod", "credentials.json", "token.json", "host.pem", "id_ed25519"):
            with self.subTest(name=name):
                self.assertTrue(secretscan.scan_path(name))

    def test_env_example_is_allowed_by_name(self):
        self.assertEqual(secretscan.scan_path("missing/.env.example"), [])


class CommandLine(unittest.TestCase):
    def run_cli(self, *paths):
        return subprocess.run(
            [sys.executable, str(HERE / "secretscan.py"), *paths], capture_output=True, text=True
        , check=False)

    def test_exit_code_is_one_on_finding_and_zero_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            dirty = Path(tmp) / "dirty.py"
            dirty.write_text(f"KEY = '{FAKES['aws access key']}'\n")
            clean = Path(tmp) / "clean.py"
            clean.write_text("print('hello')\n")
            bad = self.run_cli(str(dirty))
            self.assertEqual(bad.returncode, 1)
            self.assertIn("aws access key", bad.stdout)
            self.assertNotIn(FAKES["aws access key"], bad.stdout + bad.stderr, "the secret itself is never printed")
            self.assertEqual(self.run_cli(str(clean)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
