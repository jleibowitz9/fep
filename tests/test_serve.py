"""
Tests for the dashboard served as an application.

`dashboard/serve.py` is the only thing in this repo that accepts input from
outside the process, and two of the actions it exposes reach past this machine:
one writes to the Google Sheet and one pushes to GitHub. So the tests here are
mostly about the boundary rather than the behaviour, because the behaviour is
cli.py's and is tested where it lives.

  TestActions          every button maps to a real cli.py command
  TestCapture          a failed command reports its message instead of crashing
  TestAuthorisation    a request without this launch's token does nothing
  TestPaths            the asset route cannot be walked out of
  TestRendering        a page built to a file never claims to have a server
  TestOffline          the built copy still works with nothing behind it
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DASHBOARD = os.path.join(ROOT, "dashboard")
sys.path.insert(0, DASHBOARD)

spec = importlib.util.spec_from_file_location(
    "fep_serve", os.path.join(DASHBOARD, "serve.py"))
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)

import cli  # noqa: E402

# collect() precomputes a counterfactual board for every remaining game, so it
# is the most expensive call in this file by a wide margin. The payload does not
# change between assertions, so it is built once.
_PAYLOAD = None


def payload():
    global _PAYLOAD
    if _PAYLOAD is None:
        _PAYLOAD = serve.dashboard_build.collect(cli.YEAR)
    return _PAYLOAD


class TestActions(unittest.TestCase):
    """Every button is one cli.py command, and no command is invented here."""

    def test_every_action_is_callable(self):
        for name, (label, fn, _mutates) in serve.ACTIONS.items():
            self.assertTrue(callable(fn), "{} is not callable".format(name))
            self.assertTrue(label, "{} has no label".format(name))

    def test_the_commands_the_buttons_wrap_all_exist(self):
        # _command() closes over a name looked up at call time, so a typo here
        # would not surface until the button was pressed.
        for name in ("refresh", "dashboard", "push", "cms", "picks", "board",
                     "leverage", "week"):
            self.assertIn(name, cli.COMMANDS)

    def test_the_writes_that_leave_this_machine_ask_first(self):
        for name in serve.CONFIRM:
            self.assertIn(name, serve.ACTIONS)
        # A write that reaches the Sheet or the CMS must be in CONFIRM, or the
        # page would fire it on a single press.
        self.assertEqual(serve.CONFIRM, {"push-live", "cms-live"})


class TestCapture(unittest.TestCase):
    """cli.py reports failure by exiting with a sentence. That is not a crash."""

    def test_a_message_exit_becomes_an_error_not_an_exception(self):
        def fails(argv):
            raise SystemExit("Picks are not loaded yet.")
        result = serve._capture(fails, [])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Picks are not loaded yet.")

    def test_a_clean_exit_is_success(self):
        def fine(argv):
            print("Done.")
            raise SystemExit(0)
        result = serve._capture(fine, [])
        self.assertTrue(result["ok"])
        self.assertIn("Done.", result["log"])

    def test_output_is_captured_rather_than_printed(self):
        result = serve._capture(lambda argv: print("the board"), [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["log"], "the board")

    def test_an_unexpected_fault_still_reaches_the_page(self):
        def boom(argv):
            raise ValueError("bad csv")
        result = serve._capture(boom, [])
        self.assertFalse(result["ok"])
        self.assertIn("bad csv", result["error"])
        # The traceback belongs in the log, where it can be read, not in a
        # console nobody is watching.
        self.assertIn("Traceback", result["log"])

    def test_stdout_is_restored_afterwards(self):
        before = sys.stdout
        serve._capture(lambda argv: print("x"), [])
        self.assertIs(sys.stdout, before)
        serve._capture(lambda argv: (_ for _ in ()).throw(ValueError("x")), [])
        self.assertIs(sys.stdout, before)


class CacheIsolated(unittest.TestCase):
    """Never let a test write the cache the app actually launches from.

    This existed as a comment before it existed as a base class, and the gap
    cost a debugging cycle: a test stubbed collect() to return a marker object,
    _payload() wrote that marker to the real cache file, and the next real
    launch served a payload with one key in it.
    """

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.real_dir, self.real_file = serve.CACHE_DIR, serve.CACHE_FILE
        serve.CACHE_DIR = self.temp
        serve.CACHE_FILE = os.path.join(self.temp, "payload.json")
        self.real_collect = serve.dashboard_build.collect
        serve._payload_memo.update(key=None, data=None)

    def tearDown(self):
        serve.CACHE_DIR, serve.CACHE_FILE = self.real_dir, self.real_file
        serve.dashboard_build.collect = self.real_collect
        serve._payload_memo.update(key=None, data=None)
        shutil.rmtree(self.temp, ignore_errors=True)


class TestPayloadCache(CacheIsolated):
    """The cache is the reason the icon opens instantly, and the reason a stale
    or malformed board could be shown. Its whole job is the fingerprint."""

    def bump(self, path):
        """Move a file's mtime and put it back exactly.

        Nanoseconds, not the float seconds os.stat also offers: the fingerprint
        reads st_mtime_ns, so restoring from the float leaves the file a few
        hundred nanoseconds away from where it started and the test fails on a
        difference it created itself.
        """
        stat = os.stat(path)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10 ** 9))
        return lambda: os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    def test_the_fingerprint_moves_when_the_season_file_does(self):
        before = serve._fingerprint()
        restore = self.bump(serve.season_mod.path_for(cli.YEAR))
        try:
            self.assertNotEqual(serve._fingerprint(), before)
        finally:
            restore()
        self.assertEqual(serve._fingerprint(), before)

    def test_the_fingerprint_moves_when_the_model_does(self):
        # The trap this exists for: editing fep/analytics.py and being served
        # numbers computed by the version before the edit.
        before = serve._fingerprint()
        restore = self.bump(os.path.join(ROOT, "fep", "analytics.py"))
        try:
            self.assertNotEqual(serve._fingerprint(), before)
        finally:
            restore()
        self.assertEqual(serve._fingerprint(), before)

    def test_a_cache_written_for_another_fingerprint_is_ignored(self):
        serve._write_cache("not-the-current-key", {"board": "stale"})
        self.assertIsNone(serve._read_cache(serve._fingerprint()))

    def test_a_cache_missing_the_keys_the_page_needs_is_ignored(self):
        # Exactly the file a stubbed test wrote into the real cache once.
        serve._write_cache(serve._fingerprint(), {"marker": "rebuilt"})
        self.assertIsNone(serve._read_cache(serve._fingerprint()))

    def test_a_cache_that_is_not_a_payload_at_all_is_ignored(self):
        for junk in ([], "a string", 12, None):
            serve._write_cache(serve._fingerprint(), junk)
            self.assertIsNone(serve._read_cache(serve._fingerprint()), junk)

    def test_a_corrupt_cache_is_ignored_rather_than_raised(self):
        os.makedirs(serve.CACHE_DIR, exist_ok=True)
        with open(serve.CACHE_FILE, "w") as fh:
            fh.write("{ this is not json")
        self.assertIsNone(serve._read_cache(serve._fingerprint()))

    def shaped(self, marker):
        """A payload the guard accepts, so these test the cache and not it."""
        return dict({k: None for k in serve.REQUIRED_KEYS}, marker=marker)

    def test_a_cached_payload_is_the_one_that_comes_back(self):
        wanted = self.shaped("from the cache")
        serve._write_cache(serve._fingerprint(), wanted)
        serve.dashboard_build.collect = lambda year: self.fail(
            "the cache was ignored and the model ran anyway")
        self.assertEqual(serve._payload(), wanted)

    def test_a_second_call_does_not_run_the_model_again(self):
        serve.dashboard_build.collect = lambda year: self.shaped("computed")
        first = serve._payload()
        serve.dashboard_build.collect = lambda year: self.fail(
            "the memo was ignored and the model ran twice")
        self.assertEqual(serve._payload(), first)

    def test_forcing_recomputes_instead_of_reading_the_cache(self):
        key = serve._fingerprint()
        serve._write_cache(key, {"marker": "from the cache"})
        calls = []
        serve.dashboard_build.collect = lambda year: (calls.append(year),
                                                      {"marker": "fresh"})[1]
        self.assertEqual(serve._payload(force=True), {"marker": "fresh"})
        self.assertEqual(calls, [cli.YEAR])


class TestRequiredKeys(unittest.TestCase):
    """The cache guard checks for keys. Those keys have to be real ones."""

    def test_collect_produces_every_key_the_guard_requires(self):
        missing = serve.REQUIRED_KEYS - set(payload())
        self.assertEqual(missing, set(),
                         "the cache guard names keys collect() does not produce")


class TestLauncher(unittest.TestCase):
    """The icon starts an app, not a terminal and not a weekly run."""

    def setUp(self):
        with open(os.path.join(ROOT, "scripts", "FEP.app", "Contents",
                               "MacOS", "fep-app")) as fh:
            self.script = fh.read()

    def test_it_does_not_open_a_terminal(self):
        self.assertNotIn("open -a Terminal", self.script)

    def test_it_does_not_run_the_week(self):
        # The other icon does that. This one must never surprise anyone by
        # pulling from ESPN and freezing a snapshot on a double click.
        for command in ("cli.py week", "cli.py refresh", "cli.py push",
                        "fep-week.command"):
            self.assertNotIn(command, self.script)

    def test_it_starts_the_server_and_waits_for_it(self):
        self.assertIn("serve.py", self.script)
        self.assertIn("wait ", self.script)

    def test_quitting_the_app_stops_the_server(self):
        self.assertIn("trap ", self.script)


class TestWeeklySequence(CacheIsolated):
    """The week is three steps, and the order of them is the point.

    These run against stubs rather than the real commands: the real thing
    writes the season file, publishes a chart and pushes to GitHub, which is
    not something a test suite gets to do on its way past.
    """

    def setUp(self):
        super().setUp()
        self.calls = []
        self.original = dict(cli.COMMANDS)
        self.backup = serve._backup
        self.build = serve.dashboard_build.build
        # The rebuild step is real code, so it is left running and only the two
        # expensive things it calls are replaced.
        serve.dashboard_build.collect = lambda year: {"marker": "rebuilt"}
        serve.dashboard_build.build = lambda data: (self.calls.append("dashboard"),
                                                    os.devnull)[1]
        serve._payload_memo.update(key=None, data=None)

    def tearDown(self):
        cli.COMMANDS.clear()
        cli.COMMANDS.update(self.original)
        serve._backup = self.backup
        serve.dashboard_build.build = self.build
        super().tearDown()

    def stub(self, name, ok=True):
        def fake(argv):
            self.calls.append(name)
            print("{} ran".format(name))
            if not ok:
                raise SystemExit("{} refused".format(name))
        cli.COMMANDS[name] = fake

    def test_all_three_steps_run_in_order(self):
        self.stub("week")
        serve._backup = lambda payload=None: (self.calls.append("backup"),
                                              serve.Result(ok=True, error=None,
                                                           log="pushed"))[1]
        result = serve._week({})
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(self.calls, ["week", "dashboard", "backup"])
        self.assertIn("pushed", result["log"])

    def test_a_failed_run_is_never_committed(self):
        # The whole reason the steps are ordered: a half-written season file
        # must not be the thing that gets archived and pushed.
        self.stub("week", ok=False)
        serve._backup = lambda payload=None: (self.calls.append("backup"),
                                              serve.Result(ok=True, error=None, log=""))[1]
        result = serve._week({})
        self.assertFalse(result["ok"])
        self.assertEqual(self.calls, ["week"])
        self.assertIn("refused", result["error"])
        self.assertIn("did not run", result["log"])

    def test_a_named_week_is_passed_through(self):
        seen = []
        cli.COMMANDS["week"] = lambda argv: seen.append(list(argv))
        serve._backup = lambda payload=None: serve.Result(ok=True, error=None, log="")
        serve._week({"week": 3})
        self.assertEqual(seen, [["3"]])

    def test_no_week_means_the_current_one(self):
        seen = []
        cli.COMMANDS["week"] = lambda argv: seen.append(list(argv))
        serve._backup = lambda payload=None: serve.Result(ok=True, error=None, log="")
        serve._week({})
        self.assertEqual(seen, [[]])


class Served(unittest.TestCase):
    """A real server on a real port, started once for the whole class."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        serve.Handler.token = "test-token"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def url(self, path):
        return "http://127.0.0.1:{}{}".format(self.port, path)

    def post(self, path, body, token="test-token"):
        data = json.dumps(body).encode()
        request = urllib.request.Request(self.url(path), data=data, method="POST")
        request.add_header("Content-Type", "application/json")
        if token is not None:
            request.add_header("X-FEP-Token", token)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def get(self, path):
        try:
            with urllib.request.urlopen(self.url(path)) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


class TestAuthorisation(Served):
    """A local port is reachable by every other page in the browser."""

    def test_a_request_without_the_token_does_nothing(self):
        status, body = self.post("/api/action", {"action": "board"}, token=None)
        self.assertEqual(status, 403)
        self.assertFalse(body["ok"])

    def test_a_request_with_the_wrong_token_does_nothing(self):
        status, _ = self.post("/api/action", {"action": "board"}, token="guess")
        self.assertEqual(status, 403)

    def test_an_unknown_action_is_refused_by_name(self):
        status, body = self.post("/api/action", {"action": "push --live; rm -rf /"})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    def test_a_missing_action_is_refused(self):
        status, body = self.post("/api/action", {})
        self.assertEqual(status, 400)

    def test_state_is_readable_without_a_token(self):
        # Nothing here changes anything, and the page needs it before it has
        # rendered a single button.
        status, body = self.get("/api/state")
        self.assertEqual(status, 200)
        self.assertIn("year", json.loads(body))


class TestPaths(Served):
    """The asset route serves one folder and nothing above it."""

    def test_a_climb_out_of_assets_is_not_served(self):
        for attempt in ("/assets/../../cli.py",
                        "/assets/../serve.py",
                        "/assets/../../data/season_2026.json"):
            status, _ = self.get(attempt)
            self.assertEqual(status, 404, attempt)

    def test_an_unknown_route_is_not_served(self):
        status, _ = self.get("/data/season_2026.json")
        self.assertEqual(status, 404)


class TestRendering(unittest.TestCase):
    """The page decides what it is by whether a server announced itself."""

    def setUp(self):
        self.build = serve.dashboard_build

    def test_a_page_built_to_a_file_has_no_live_hook(self):
        page = self.build.render(payload())
        self.assertNotIn("__LIVE__", page)
        # The front end reads window.FEP_LIVE, so the name is in the page's own
        # source either way. What must be absent is anything assigning it: that
        # assignment is the whole of how a page learns it has a server.
        self.assertNotIn("window.FEP_LIVE=", page)
        self.assertNotIn("window.FEP_LIVE =", page)

    def test_a_served_page_carries_the_launch_token(self):
        page = self.build.render(
            payload(), live='<script>window.FEP_LIVE={"token":"abc"};</script>')
        self.assertIn("FEP_LIVE", page)
        self.assertIn('"abc"', page)

    def test_no_placeholder_survives_either_way(self):
        data = payload()
        for page in (self.build.render(data), self.build.render(data, live="<b></b>")):
            for placeholder in ("__DATA__", "__CHART__", "__LIVE__"):
                self.assertNotIn(placeholder, page)


class TestOffline(unittest.TestCase):
    """The built copy is still the thing that works when nothing is running."""

    def test_the_file_copy_falls_back_to_copying_commands(self):
        page = serve.dashboard_build.render(payload())
        # LIVE is false without the hook, and these are the two commands the
        # page hands over in that state.
        self.assertIn("python3 cli.py week", page)
        self.assertIn("python3 cli.py push --live", page)

    def test_the_page_never_hardcodes_a_path_outside_the_repo(self):
        with open(os.path.join(DASHBOARD, "serve.py")) as fh:
            source = fh.read()
        self.assertNotIn("~/Library", source)
        self.assertNotIn("/Users/", source)


class TestProse(unittest.TestCase):
    """The house rule, applied to the new surfaces too."""

    def test_no_em_or_en_dashes_in_the_new_files(self):
        for path in (os.path.join(DASHBOARD, "serve.py"),
                     os.path.join(ROOT, "scripts", "fep-app.command")):
            with open(path) as fh:
                text = fh.read()
            self.assertNotIn("—", text, path)
            self.assertNotIn("–", text, path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
