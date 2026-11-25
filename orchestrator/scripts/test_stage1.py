#!/usr/bin/env python3
"""Self-check for changed.py, bigfile.py, usagetier.py and dashboard.py:  python3 test_stage1.py   (uses a temp state dir, touches nothing else)."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).parent


class T(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.env = {**os.environ, "AGENT_STATE_DIR": str(self.d / "state")}

    def run_(self, script, *args):
        p = subprocess.run([sys.executable, "-I", str(HERE / script), *map(str, args)], capture_output=True, text=True, env=self.env, check=False)
        return p.returncode, p.stdout, p.stderr

    # ---- changed.py
    def test_changed(self):
        f = self.d / "a.txt"; f.write_text("one")
        self.assertEqual(self.run_("changed.py", "check", "k", "--file", f)[0], 0)      # first time = changed
        self.assertEqual(self.run_("changed.py", "check", "k", "--file", f)[0], 3)      # same
        f.write_text("two")
        self.assertEqual(self.run_("changed.py", "peek", "k", "--file", f)[0], 0)       # peek does not record
        self.assertEqual(self.run_("changed.py", "peek", "k", "--file", f)[0], 0)
        self.run_("changed.py", "mark", "k", "--file", f)
        self.assertEqual(self.run_("changed.py", "check", "k", "--file", f)[0], 3)
        self.assertEqual(self.run_("changed.py", "check", "k", "--file", self.d / "missing")[0], 2)   # error != unchanged
        self.assertEqual(self.run_("changed.py", "check", "k", "--file", f)[0], 3)      # error recorded nothing
        self.assertEqual(self.run_("changed.py", "check", "c", "--", sys.executable, "-c", "print(1)")[0], 0)
        self.assertEqual(self.run_("changed.py", "check", "c", "--", sys.executable, "-c", "print(1)")[0], 3)
        self.assertEqual(self.run_("changed.py", "check", "c", "--", sys.executable, "-c", "import sys;sys.exit(1)")[0], 2)
        self.assertEqual(self.run_("changed.py", "check", "../x", "--file", f)[0], 2)  # bad key rejected
        self.run_("changed.py", "reset", "k")
        self.assertEqual(self.run_("changed.py", "check", "k", "--file", f)[0], 0)
        (self.d / "dir").mkdir(); (self.d / "dir" / "v.mp4").write_text("x")
        self.assertEqual(self.run_("changed.py", "check", "d", "--dir", self.d / "dir")[0], 0)
        self.assertEqual(self.run_("changed.py", "check", "d", "--dir", self.d / "dir")[0], 3)
        (self.d / "dir" / "w.mp4").write_text("y")
        self.assertEqual(self.run_("changed.py", "check", "d", "--dir", self.d / "dir")[0], 0)

    # ---- bigfile.py
    HEAD = "id,date,text\n"
    def rows(self, ids):
        return "".join(f'{i},2026-11-{10 + i:02d},"line {i}\nsecond ""quoted"" line"\n' for i in ids)

    def test_new_view_trim(self):
        f = self.d / "cal.csv"; f.write_text(self.HEAD + self.rows(range(1, 6)))
        rc, out, _ = self.run_("bigfile.py", "new", f, "--consumer", "a")
        self.assertEqual(rc, 0); self.assertEqual(out.count("\n"), 6)                    # header + 5 rows, multi-line cells joined
        self.assertIn("id,date,text", out); self.assertIn("line 3 second", out)
        self.assertEqual(self.run_("bigfile.py", "new", f, "--consumer", "a")[0], 3)     # nothing new
        self.assertEqual(self.run_("bigfile.py", "new", f, "--consumer", "b", "--max-rows", 2)[1].count("\n"), 4)  # own place, paging
        rc, out, _ = self.run_("bigfile.py", "new", f, "--consumer", "b", "--max-rows", 2, "--peek")   # peek: place not moved
        self.assertIn("line 3", out); self.assertIn("1 more unread", out)
        with open(f, "a", encoding="utf-8") as fh: fh.write(self.rows([6]) + '7,2026-11-17,"half writ')      # row 7 still being written
        rc, out, _ = self.run_("bigfile.py", "new", f, "--consumer", "a")
        self.assertIn("line 6", out); self.assertNotIn("half writ", out)
        with open(f, "a", encoding="utf-8") as fh: fh.write('ten"\n')                                        # finish row 7
        rc, out, _ = self.run_("bigfile.py", "new", f, "--consumer", "a")
        self.assertIn("half written", out)
        rc, out, _ = self.run_("bigfile.py", "view", f, "--where", "date>=2026-11-14", "--where", "date<=2026-11-15", "--cols", "id,date")
        self.assertEqual(out.strip().splitlines(), ["id,date", "4,2026-11-14", "5,2026-11-15"])
        self.assertEqual(self.run_("bigfile.py", "view", f, "--where", "nope=1")[0], 2)    # unknown column: exit 2
        # trim: dry run changes nothing, apply keeps header + newest, archive gets the rest byte-exact
        before = f.read_bytes()
        rc, out, _ = self.run_("bigfile.py", "trim", f, "--keep-rows", 3)
        self.assertEqual(rc, 0); self.assertIn("dry run", out); self.assertEqual(f.read_bytes(), before)
        arch = self.d / "arch"
        self.assertEqual(self.run_("bigfile.py", "trim", f, "--keep-rows", 3, "--archive-dir", arch, "--apply")[0], 0)
        kept = f.read_text(encoding="utf-8")
        self.assertTrue(kept.startswith(self.HEAD)); self.assertEqual(kept, self.HEAD + self.rows([5, 6]) + '7,2026-11-17,"half written"\n')
        self.assertEqual((arch / "cal.archive.csv").read_text(encoding="utf-8"), self.HEAD + self.rows(range(1, 5)))   # rows 1-4 moved
        self.assertTrue(before.decode().endswith(kept[len(self.HEAD):]))                  # kept rows are the original bytes
        # consumer "a" had read everything: after trim it must see only NEW rows, none twice, none lost
        self.assertEqual(self.run_("bigfile.py", "new", f, "--consumer", "a")[0], 3)
        with open(f, "a", encoding="utf-8") as fh: fh.write(self.rows([8]))
        rc, out, _ = self.run_("bigfile.py", "new", f, "--consumer", "a")
        self.assertIn("line 8", out); self.assertNotIn("line 7", out)
        # consumer "b" had read 2 rows then trim moved rows 1-4: told so, continues from oldest kept
        rc, out, _ = self.run_("bigfile.py", "new", f, "--consumer", "b")
        self.assertIn("moved to the archive", out); self.assertIn("line 5", out)
        # trim refuses a half-written file
        with open(f, "a", encoding="utf-8") as fh: fh.write("9,2026-11-19,part")
        self.assertEqual(self.run_("bigfile.py", "trim", f, "--keep-rows", 1, "--apply")[0], 2)
        # shortened/replaced file is noticed
        f.write_text(self.HEAD + self.rows([1]))
        self.assertIn("fewer rows", self.run_("bigfile.py", "new", f, "--consumer", "a")[1])

    def test_stray_and_unclosed_quotes(self):
        f = self.d / "c.csv"; f.write_text('id,text\n1,"a 6"" frame, quoted"\n2,a 6" frame unquoted\n')
        self.assertEqual(self.run_("bigfile.py", "new", f, "--consumer", "q")[0], 0)
        with open(f, "a", encoding="utf-8") as fh: fh.write('3,27" monitor\n4,fine\n')                       # the stray quote must not swallow these
        rc, out, _ = self.run_("bigfile.py", "new", f, "--consumer", "q")
        self.assertEqual(rc, 0); self.assertIn('3,"27"" monitor"', out); self.assertIn("4,fine", out)
        with open(f, "a", encoding="utf-8") as fh: fh.write('5,"never closed\n')                              # genuinely unclosed cell, newline-terminated
        rc, out, err = self.run_("bigfile.py", "new", f, "--consumer", "q")
        self.assertEqual(rc, 2); self.assertIn("unclosed quote", err)                       # an error, never "no new rows"
        self.assertEqual(self.run_("bigfile.py", "trim", f, "--keep-rows", 1, "--apply")[0], 2)
        with open(f, "a", encoding="utf-8") as fh: fh.write('more text"\n')                                   # writer finishes the cell
        rc, out, _ = self.run_("bigfile.py", "new", f, "--consumer", "q")
        self.assertEqual(rc, 0); self.assertIn("never closed more text", out)

    def test_lines_mode(self):
        f = self.d / "claims.log"; f.write_text("a\nb\nc\n")
        self.assertEqual(self.run_("bigfile.py", "new", f, "--consumer", "x")[1].split(), ["a", "b", "c"])
        f.write_text("a\nb\nc\nd\n")
        self.assertEqual(self.run_("bigfile.py", "new", f, "--consumer", "x")[1].split(), ["d"])
        self.assertEqual(self.run_("bigfile.py", "trim", f, "--keep-chars", 4, "--archive-dir", self.d, "--apply")[0], 0)
        self.assertEqual(f.read_text(encoding="utf-8"), "c\nd\n"); self.assertEqual((self.d / "claims.log.archive").read_text(encoding="utf-8"), "a\nb\n")

    # ---- usagetier.py, dashboard.py, /tier
    def flag(self, scope):
        f = self.d / "state" / ("pause.json" if scope == "*" else f"pause.{scope}.json")
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def test_usagetier(self):
        ut = lambda *a: self.run_("usagetier.py", *a)
        self.assertEqual(ut("set", 50)[0], 2)                                               # no config yet
        self.assertEqual(ut("init")[0], 0); self.assertEqual(ut("init")[0], 2)              # never overwrites
        self.assertEqual(ut("set", 101)[0], 2); self.assertEqual(ut("set", "x")[0], 2)
        self.assertEqual(ut("set", 40)[0], 0); self.assertIsNone(self.flag("bhuvam"))       # normal pauses nothing
        self.assertEqual(ut("set", 90)[0], 0)
        for b in ("bhuvam", "kabir", "chitra", "drishti"): self.assertTrue(self.flag(b)["reason"].startswith("usage-tier:"))
        self.assertTrue(self.flag("kabir")["until"])                                        # timed: lifts itself
        self.assertIsNone(self.flag("vivek"))
        self.run_("pausectl.py", "pause", "--bot", "vivek", "--reason", "by hand")          # manual pauses survive both ways
        self.run_("pausectl.py", "pause", "--bot", "kabir", "--reason", "manual kabir")
        _rc, out, _ = ut("set", 90); self.assertIn("left alone", out); self.assertEqual(self.flag("kabir")["reason"], "manual kabir")
        self.assertEqual(ut("set", 62)[0], 0)                                               # light: only bhuvam stays paused
        self.assertIsNotNone(self.flag("bhuvam")); self.assertIsNone(self.flag("chitra")); self.assertIsNone(self.flag("drishti"))
        self.assertEqual(self.flag("kabir")["reason"], "manual kabir"); self.assertEqual(self.flag("vivek")["reason"], "by hand")
        self.assertEqual(ut("set", 97)[0], 0); self.assertTrue(self.flag("*")["reason"].startswith("usage-tier:"))   # "*" = global
        self.assertEqual(ut("set", 10)[0], 0)
        for s in ("*", "bhuvam"): self.assertIsNone(self.flag(s))
        self.assertEqual(self.flag("vivek")["reason"], "by hand")
        self.assertIn("tier normal", ut("status")[1])

    def test_usagetier_bad_config_changes_nothing(self):
        cfg = self.d / "bad.json"
        for bad in ({"tiers": [{"name": "a", "min_pct": 10, "pause_bots": []}]},                      # lowest tier not 0
                    {"tiers": [{"name": "a", "min_pct": 0, "pause_bots": ["../x"]}]},                 # bad bot name
                    {"tiers": [{"name": "a", "min_pct": 0, "pause_bots": []}], "restore_after": "soon"}):
            cfg.write_text(json.dumps(bad))
            self.assertEqual(self.run_("usagetier.py", "--config", cfg, "set", 50)[0], 2)
        self.assertEqual(list((self.d / "state").glob("pause*")), [])

    def test_dashboard_and_tier_command(self):
        self.assertEqual(self.run_("usagetier.py", "init")[0], 0); self.run_("usagetier.py", "set", 90)
        self.run_("statusupdate.py", "kabir", "x-replies", "ok", "--count", "drafted=45")
        self.run_("statusupdate.py", "vivek", "factcheck", "failed", "--note", "<b>boom</b>")
        self.run_("queuectl.py", "add", "--lane", "claude", "--kind", "drafts", "--path", "/f.md", "--note", "<script>x</script>")
        rc, text, _ = self.run_("dashboard.py"); self.assertEqual(rc, 0)
        for s in ("saving", "kabir", "factcheck | failed", "failed in 24h", "drafts"): self.assertIn(s, text)
        out = self.d / "page" / "d.html"; self.assertEqual(self.run_("dashboard.py", "--html", out)[0], 0)
        page = out.read_text(encoding="utf-8"); self.assertNotIn("<script>x", page); self.assertIn("&lt;script&gt;", page)    # escaped
        self.assertLess(len(page), 8000)
        sys.path.insert(0, str(HERE)); os.environ["AGENT_STATE_DIR"] = self.env["AGENT_STATE_DIR"]
        import telegram_control as tc
        self.assertIn("tier saving", tc.handle("/tier"))
        self.assertIn("tier normal", tc.handle("/tier 5")); self.assertIn("Use /tier", tc.handle("/tier 5; rm -rf /"))
        self.assertIn("Use /tier", tc.handle("/tier 1 2"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
