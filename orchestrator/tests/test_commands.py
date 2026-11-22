"""Every Telegram command answers help without network or model, and /menu lists them all."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from orchestrator import commands


class NoNetwork:
    def request(self, *args, **kwargs):
        raise AssertionError("help must not touch the network")


class Commands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_every_command_answers_every_help_word(self):
        for command in commands.table():
            for word in ("", "help", "-help", "--help", "-h", "?", "HELP"):
                with self.subTest(command=command.name, word=word), \
                        mock.patch("orchestrator.brief.net.UrllibHttp", NoNetwork):
                    reply = commands.dispatch(command.name, word)
                    self.assertEqual(reply, command.help_text)
                    self.assertIn(f"/{command.name}", reply)

    def test_menu_lists_every_command(self):
        menu = commands.dispatch("menu", "")
        for command in commands.table():
            self.assertIn(f"/{command.name} — {command.summary}", menu)
        self.assertIn("/help", menu, "points to Hermes' own command list")

    def test_plugin_registers_menu_and_every_command(self):
        spec = importlib.util.spec_from_file_location("orch_plugin", ROOT / "orchestrator/plugin/__init__.py")
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)
        registered = {}
        skills = {}

        class Ctx:
            def register_command(self, name, handler, **kw):
                registered[name] = handler

            def register_hook(self, name, fn):
                pass

            def register_skill(self, name, path, description=""):
                skills[name] = Path(path)

        plugin.register(Ctx())
        self.assertEqual(set(registered), {"menu"} | {c.name for c in commands.table()})
        self.assertIn("/brief", registered["menu"]())
        self.assertIn("/brief more", registered["brief"]("-help"))
        self.assertTrue(skills["outreach"].is_file(), "the agent's draft-only skill ships with the plugin")
        self.assertTrue(skills["hr-payslips"].is_file())


if __name__ == "__main__":
    unittest.main()
