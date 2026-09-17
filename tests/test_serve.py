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
  TestBackupHonesty    a backup that failed must not report success, and must
                       stage only what the run itself wrote
  TestDeploymentHealth the page said "Apps Script ready" because a file existed
                       on this laptop, which is not a fact about a spreadsheet
  TestPresence         the page says when it is on screen, and only the page,
                       by holding a connection rather than beating a timer
  TestSecondTap        a tap while the app is up raises the window it has,
                       and a raise that did not happen opens one instead
  TestReadiness        the board is ready or it is being prepared, once
  TestLoadingPage      a first load shows something rather than a blank window
  TestLastRun          the server, not the URL, knows whether the last week
                       run recorded anything and whether the Sheet has it
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
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
        for name in ("refresh", "dashboard", "cms", "picks", "board",
                     "leverage", "week"):
            self.assertIn(name, cli.COMMANDS)

    def test_the_writes_that_leave_this_machine_ask_first(self):
        for name in serve.CONFIRM:
            self.assertIn(name, serve.ACTIONS)
        # A write that reaches the CMS must be in CONFIRM, or the page would
        # fire it on a single press.
        self.assertEqual(serve.CONFIRM, {"cms-live"})


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


class TestWindow(unittest.TestCase):
    """The page should arrive in a window, not inside a browser's furniture."""

    def setUp(self):
        self.real_chrome = serve.CHROME
        self.real_popen = serve.subprocess.Popen
        self.real_webbrowser = serve.webbrowser.open
        self.opened = []
        serve.webbrowser.open = lambda url: self.opened.append(("browser", url))
        serve.subprocess.Popen = lambda cmd, **kw: self.opened.append(("chrome", cmd))
        # The real marker is what the next Dock tap reads. A test must not
        # leave it looking as if a window is on its way.
        self.real_opening = serve.OPENING_FILE
        serve.OPENING_FILE = os.path.join(tempfile.mkdtemp(), "opening.txt")
        self.env = os.environ.get("FEP_BROWSER")
        os.environ.pop("FEP_BROWSER", None)

    def tearDown(self):
        serve.CHROME = self.real_chrome
        serve.subprocess.Popen = self.real_popen
        serve.webbrowser.open = self.real_webbrowser
        shutil.rmtree(os.path.dirname(serve.OPENING_FILE), ignore_errors=True)
        serve.OPENING_FILE = self.real_opening
        if self.env is None:
            os.environ.pop("FEP_BROWSER", None)
        else:
            os.environ["FEP_BROWSER"] = self.env

    def test_chrome_gets_the_app_flag_when_it_is_installed(self):
        serve.CHROME = __file__  # any path that exists
        self.assertEqual(serve._open_window("http://127.0.0.1:8765/"), "chrome-app")
        kind, cmd = self.opened[0]
        self.assertEqual(kind, "chrome")
        self.assertIn("--app=http://127.0.0.1:8765/", cmd)

    def test_a_machine_without_chrome_uses_the_default_browser(self):
        serve.CHROME = "/nowhere/Google Chrome"
        self.assertEqual(serve._open_window("http://x/"), "default-browser")
        self.assertEqual(self.opened, [("browser", "http://x/")])

    def test_the_preference_can_be_turned_off(self):
        serve.CHROME = __file__
        os.environ["FEP_BROWSER"] = "default"
        self.assertEqual(serve._open_window("http://x/"), "default-browser")
        self.assertEqual(self.opened, [("browser", "http://x/")])

    def test_a_chrome_that_will_not_start_falls_back(self):
        serve.CHROME = __file__
        def boom(cmd, **kw):
            raise OSError("no")
        serve.subprocess.Popen = boom
        self.assertEqual(serve._open_window("http://x/"), "default-browser")
        self.assertEqual(self.opened, [("browser", "http://x/")])


class TestRunningServer(CacheIsolated):
    """Finding the server that is already up, and not finding a dead one."""

    def setUp(self):
        super().setUp()
        self.real_url_file = serve.URL_FILE
        serve.URL_FILE = os.path.join(self.temp, "url.txt")

    def tearDown(self):
        serve.URL_FILE = self.real_url_file
        super().tearDown()

    def test_a_url_written_by_a_live_process_is_read_back(self):
        serve._write_url("http://127.0.0.1:9999/")
        self.assertEqual(serve._recorded_url(), "http://127.0.0.1:9999/")

    def test_a_url_left_by_a_dead_process_is_ignored(self):
        # SIGTERM skips the cleanup, so this file routinely outlives its
        # server. Trusting it made the next launch decide the app was already
        # open and exit without starting anything.
        with open(serve.URL_FILE, "w") as fh:
            fh.write("999999\nhttp://127.0.0.1:9999/")
        self.assertIsNone(serve._recorded_url())

    def test_a_malformed_url_file_is_ignored(self):
        for junk in ("", "not a pid", "123", "abc\nhttp://x/"):
            with open(serve.URL_FILE, "w") as fh:
                fh.write(junk)
            self.assertIsNone(serve._recorded_url(), junk)

    def test_a_missing_url_file_is_ignored(self):
        self.assertIsNone(serve._recorded_url())

    def test_clearing_removes_it(self):
        serve._write_url("http://127.0.0.1:9999/")
        serve._clear_url()
        self.assertIsNone(serve._recorded_url())


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

    def test_it_starts_the_server(self):
        self.assertIn("serve.py", self.script)

    def test_it_detaches_the_server_and_exits(self):
        # macOS only re-runs a bundle's executable when the app is not already
        # running, so a launcher that stays alive to own the server makes the
        # second tap of the icon do nothing at all. The server is detached and
        # this exits.
        self.assertIn("nohup", self.script)
        self.assertNotIn('wait "$PID"', self.script)

    def test_it_stops_waiting_once_the_server_answers(self):
        # Rather than a fixed sleep, which is either too short to catch a
        # failure or long enough to be the slowest part of the launch.
        self.assertIn("/api/state", self.script)


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
        self.assertIn("python3 cli.py cms --live", page)

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


# ---------------------------------------------------------------------------
# September 2026, finding 4: a failed backup could report success
# ---------------------------------------------------------------------------

class TestBackupHonesty(unittest.TestCase):
    """The page said the week was on GitHub when nothing had been committed.

    `git add` was unchecked and a failed `git commit` was only logged; with
    nothing then waiting ahead of origin/main the next branch returned success.
    So an index lock read as a finished, archived week.
    """

    def setUp(self):
        self.calls = []
        self.original = serve._git
        self.manifest = serve.manifest.read

    def tearDown(self):
        serve._git = self.original
        serve.manifest.read = self.manifest

    def fake_git(self, **fail):
        """A git that answers plausibly, failing whichever verbs are named."""
        def run(*args):
            self.calls.append(args)
            verb = args[0]
            if verb in fail:
                return 1, fail[verb]
            if verb == "status":
                return 0, " M data/season_2026.json"
            if verb == "log":
                return 0, ""          # nothing waiting: the dangerous case
            return 0, ""
        serve._git = run

    def test_a_failed_stage_is_a_failure(self):
        self.fake_git(add="fatal: Unable to create '.git/index.lock': File exists.")
        result = serve._backup()
        self.assertFalse(result["ok"])
        self.assertIn("stage", result["error"])
        self.assertIn("index.lock", result["log"])

    def test_a_failed_stage_never_reaches_the_commit(self):
        self.fake_git(add="fatal: index.lock")
        serve._backup()
        self.assertNotIn("commit", [c[0] for c in self.calls])

    def test_a_failed_commit_is_not_reported_as_up_to_date(self):
        # Codex's reproduction, exactly: commit fails, nothing is ahead of
        # origin/main, and the old code returned ok=True saying GitHub had it.
        self.fake_git(commit="fatal: Unable to create '.git/index.lock': File exists.")
        result = serve._backup()
        self.assertFalse(result["ok"])
        self.assertNotIn("up to date", result["log"])
        self.assertIn("Nothing was committed", result["log"])

    def test_a_failed_commit_never_reaches_the_push(self):
        self.fake_git(commit="fatal: index.lock")
        serve._backup()
        self.assertNotIn("push", [c[0] for c in self.calls])

    def test_being_unable_to_see_github_is_not_being_up_to_date(self):
        self.fake_git(log="fatal: bad revision 'origin/main'")
        result = serve._backup()
        self.assertFalse(result["ok"])
        self.assertIn("compare", result["error"])

    def test_a_clean_tree_is_still_success(self):
        def run(*args):
            self.calls.append(args)
            return 0, ""      # nothing dirty, nothing ahead
        serve._git = run
        result = serve._backup()
        self.assertTrue(result["ok"])
        self.assertIn("Nothing new to commit", result["log"])


class TestBackupStagesOnlyTheRun(unittest.TestCase):
    """Staging three whole directories can commit another session's work."""

    def setUp(self):
        self.original = serve.manifest.read

    def tearDown(self):
        serve.manifest.read = self.original

    def test_the_run_manifest_decides_what_is_staged(self):
        serve.manifest.read = lambda: {
            "week": 4, "paths": ["data/season_2026.json",
                                 "newsletters/week-04/statpack.md"]}
        self.assertEqual(serve._backup_paths(),
                         ["data/season_2026.json",
                          "newsletters/week-04/statpack.md"])

    def test_without_a_manifest_it_falls_back_to_the_directories(self):
        serve.manifest.read = lambda: None
        self.assertEqual(serve._backup_paths(), list(serve.BACKUP_PATHS))

    def test_an_empty_manifest_falls_back_rather_than_staging_nothing(self):
        serve.manifest.read = lambda: {"week": 4, "paths": []}
        self.assertEqual(serve._backup_paths(), list(serve.BACKUP_PATHS))


class TestRunManifest(unittest.TestCase):
    """What the run wrote down about itself."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "last_run.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_paths_are_recorded_relative_to_the_repository(self):
        target = os.path.join(ROOT, "cli.py")
        serve.manifest.write(4, [target], path=self.path)
        self.assertEqual(serve.manifest.read(self.path)["paths"], ["cli.py"])

    def test_a_path_that_no_longer_exists_is_dropped(self):
        serve.manifest.write(4, [os.path.join(ROOT, "cli.py")], path=self.path)
        with open(self.path) as fh:
            data = json.load(fh)
        data["paths"].append("newsletters/week-99/gone.md")
        with open(self.path, "w") as fh:
            json.dump(data, fh)
        self.assertEqual(serve.manifest.read(self.path)["paths"], ["cli.py"])

    def test_a_corrupt_manifest_is_ignored_rather_than_raised(self):
        with open(self.path, "w") as fh:
            fh.write("{not json")
        self.assertIsNone(serve.manifest.read(self.path))

    def test_a_missing_manifest_is_ignored(self):
        self.assertIsNone(serve.manifest.read(self.path))

    def test_a_manifest_that_cannot_be_written_is_not_fatal(self):
        # A run that has already succeeded must not fail over its own notes.
        self.assertIsNone(
            serve.manifest.write(4, ["cli.py"], path="/nope/last_run.json"))


# ---------------------------------------------------------------------------
# September 2026, finding 1: readiness was inferred from a file existing
# ---------------------------------------------------------------------------

class TestDeploymentHealth(unittest.TestCase):
    """Nothing about a deployment is inferred; it is asked, or it is unknown."""

    def setUp(self):
        self.health = serve.sheets.deployment_health
        serve._health_memo.update(at=0.0, data=None)

    def tearDown(self):
        serve.sheets.deployment_health = self.health
        serve._health_memo.update(at=0.0, data=None)

    def stub(self, *rows):
        serve.sheets.deployment_health = lambda *a, **k: list(rows)

    def row(self, name, **over):
        base = {"name": name, "configured": True, "reachable": True,
                "version": "2026.09.09-a", "local": "2026.09.09-a",
                "current": True, "error": None, "checked_at": "now"}
        base.update(over)
        return base

    def test_unchecked_is_reported_as_unchecked(self):
        # Never "ready". The old page said that whenever a config file existed.
        state = serve._health_state()
        self.assertFalse(state["checked"])
        self.assertEqual(state["deployments"], [])

    def test_the_state_never_probes_the_network_on_its_own(self):
        serve.sheets.deployment_health = lambda *a, **k: self.fail(
            "a page load must not wait on Google")
        serve._health_state()

    def test_a_check_fills_the_state_in(self):
        self.stub(self.row("legacy"), self.row("cms"))
        serve._health()
        state = serve._health_state()
        self.assertTrue(state["checked"])
        self.assertEqual([d["name"] for d in state["deployments"]],
                         ["legacy", "cms"])

    def test_a_stale_check_is_not_believed(self):
        self.stub(self.row("legacy"))
        serve._health()
        serve._health_memo["at"] -= serve.HEALTH_TTL + 1
        self.assertFalse(serve._health_state()["checked"])

    def test_a_deployment_with_no_version_stamp_is_named_as_older(self):
        self.stub(self.row("legacy", version=None, current=False))
        result = serve._health()
        self.assertIn("no version stamp", result["log"])
        self.assertIn("Manage deployments", result["log"])

    def test_a_deployment_that_did_not_answer_is_told_apart_from_a_stale_one(self):
        # Different problems, different first thing to try.
        self.stub(self.row("cms", reachable=False, version=None, current=False,
                           error="URLError: timed out"))
        self.assertIn("did not answer", serve._health()["log"])

    def test_a_current_pair_says_so_and_asks_for_nothing(self):
        self.stub(self.row("legacy"), self.row("cms"))
        log = serve._health()["log"]
        self.assertIn("running 2026.09.09-a", log)
        self.assertNotIn("redeploying", log)

    def test_checking_writes_nothing_so_it_asks_for_no_confirmation(self):
        self.assertIn("health", serve.ACTIONS)
        self.assertNotIn("health", serve.CONFIRM)


class TestTheWriteIsVersionGuarded(unittest.TestCase):
    """A write never lands on a deployment running different code.

    Editing Code.gs does not redeploy it, so the file in this checkout and the
    code actually running can differ with nothing to show for it. That has
    happened twice, once silently rewriting rows a newer guard would have
    refused. These tests used to cover the weekly `B2:M20` push as well; that
    writer was retired with the legacy spreadsheet, and the CMS tables are now
    the only thing here that reaches Google at all.
    """

    def setUp(self):
        self.season = serve.season_mod.load(2026)
        self.probe = serve.sheets.deployed_code_version
        self.call = serve.sheets._call_appsscript
        self.calls = []
        serve.sheets._call_appsscript = lambda *a, **k: self.calls.append(a) or {
            "ok": True, "total": 0}

    def tearDown(self):
        serve.sheets.deployed_code_version = self.probe
        serve.sheets._call_appsscript = self.call

    def test_a_stale_deployment_refuses_the_write(self):
        serve.sheets.deployed_code_version = lambda *a, **k: "2020.01.01-a"
        with self.assertRaises(serve.sheets.SheetError) as caught:
            serve.sheets.push_tables(self.season, only=["seasons"])
        self.assertIn("does not redeploy", str(caught.exception))

    def test_a_deployment_with_no_stamp_refuses_the_write(self):
        # No stamp at all means code from before the stamp existed, which is
        # not "unknown, probably fine".
        serve.sheets.deployed_code_version = lambda *a, **k: None
        with self.assertRaises(serve.sheets.SheetError):
            serve.sheets.push_tables(self.season, only=["seasons"])

    def test_a_refused_write_sends_nothing(self):
        serve.sheets.deployed_code_version = lambda *a, **k: "2020.01.01-a"
        with self.assertRaises(serve.sheets.SheetError):
            serve.sheets.push_tables(self.season, only=["seasons"])
        self.assertEqual(self.calls, [])

    def test_a_dry_run_never_asks_the_network(self):
        serve.sheets.deployed_code_version = lambda *a, **k: self.fail(
            "a preview must not reach outside this machine")
        result = serve.sheets.push_tables(self.season, dry_run=True,
                                          only=["seasons"])
        self.assertTrue(result[0]["dry_run"])
        self.assertEqual(self.calls, [])


class TestTheLegacySheetIsGone(unittest.TestCase):
    """September 2026: `Weighted - MASTER` was retired, not left to rot.

    Nothing read it any more -- the chart had moved to the immutable
    chart-data files and the standings to the CMS `standings` table. Leaving
    the writer in place would have meant a second deployment to keep current
    and a second health row that was permanently amber, which is how a panel
    teaches you to stop reading it.
    """

    def test_the_sheet_push_is_not_a_command(self):
        self.assertNotIn("push", cli.COMMANDS)

    def test_no_button_offers_it(self):
        self.assertNotIn("push-live", serve.ACTIONS)
        self.assertNotIn("push-preview", serve.ACTIONS)

    def test_the_writer_and_its_transports_are_gone(self):
        for name in ("push", "push_via_appsscript", "push_via_service_account",
                     "targets", "as_rows", "assert_safe_range",
                     "credentials_available"):
            self.assertFalse(hasattr(serve.sheets, name),
                             "sheets.{} outlived the legacy sheet".format(name))

    def test_health_reports_the_one_deployment_that_is_left(self):
        original = serve.sheets._probe
        serve.sheets._probe = lambda url, **k: ("2026.09.09-a", None)
        try:
            rows = serve.sheets.deployment_health()
        finally:
            serve.sheets._probe = original
        self.assertEqual([r["name"] for r in rows], ["cms"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestPresence(Served):
    """The server cannot see its window. The page tells it, and only the page.

    By holding a connection open, not by beating on a timer: a minimised
    window's timers are throttled to one wake a minute, and a minimised
    window is exactly the one whose icon gets tapped.
    """

    def setUp(self):
        serve._forget_presence()
        self.held = []
        self.real_opening = serve.OPENING_FILE
        serve.OPENING_FILE = os.path.join(tempfile.mkdtemp(), "opening.txt")

    def tearDown(self):
        for held in self.held:
            held.close()
        self.settle(lambda: not serve._page_open())
        shutil.rmtree(os.path.dirname(serve.OPENING_FILE), ignore_errors=True)
        serve.OPENING_FILE = self.real_opening
        serve._forget_presence()

    def state(self):
        _, body = self.get("/api/state")
        return json.loads(body)

    class Held:
        """One presence connection, closed the way a closing window closes it.

        http.client keeps the socket alive for as long as the response object
        holds it, so closing the connection alone leaves the server talking
        to a socket that is still open. Both have to go.
        """

        def __init__(self, conn, response):
            self.conn, self.response, self.status = conn, response, response.status

        def close(self):
            self.response.close()
            self.conn.close()

    def hold(self, path, token="test-token"):
        """Open a presence connection and keep it, the way a page does."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers={"X-FEP-Token": token} if token else {})
        held = self.Held(conn, conn.getresponse())
        self.held.append(held)
        return held, held.response

    def settle(self, condition, within=3.0):
        deadline = time.time() + within
        while not condition() and time.time() < deadline:
            time.sleep(0.05)
        return condition()

    def test_a_page_that_has_not_connected_is_not_open(self):
        self.assertEqual(self.state()["page"], {"open": False, "opening": False})

    def test_a_held_connection_marks_the_page_open(self):
        _, response = self.hold("/api/presence")
        self.assertEqual(response.status, 200)
        self.assertEqual(self.state()["page"], {"open": True, "opening": False})

    def test_closing_the_window_closes_it(self):
        # Nothing is said on the way out. The connection drops with the page,
        # and the server notices within a tick or two.
        conn, _ = self.hold("/api/presence")
        self.assertTrue(self.state()["page"]["open"])
        conn.close()
        self.assertTrue(self.settle(lambda: not self.state()["page"]["open"]))

    def test_two_windows_are_a_count_not_a_timestamp(self):
        # The reload after a run is one page closing as another opens, in
        # either order. A count survives that; the old "last word" did not.
        first, _ = self.hold("/api/presence")
        second, _ = self.hold("/api/presence")
        first.close()
        time.sleep(3 * serve.PRESENCE_TICK)
        self.assertTrue(self.state()["page"]["open"])
        second.close()
        self.assertTrue(self.settle(lambda: not self.state()["page"]["open"]))

    def test_a_connection_without_the_token_is_refused(self):
        # Any page in the browser can reach this port. None of them gets to
        # claim to be the app, because "open" is what stops a window opening.
        _, response = self.hold("/api/presence", token=None)
        self.assertEqual(response.status, 403)
        self.assertFalse(self.state()["page"]["open"])

    def test_the_waiting_page_counts_as_a_window_on_its_way(self):
        # It has no token, and it is on screen: a tap during the wait must
        # raise it, not open a second window beside it.
        _, response = self.hold("/api/preparing", token=None)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.state()["page"], {"open": False, "opening": True})
        self.assertTrue(serve._page_open())

    def test_a_page_arriving_clears_the_opening_marker(self):
        # Left in place, a window closed and reopened inside the marker's
        # twenty seconds was "raised" rather than opened, and nothing appeared.
        serve._note_opening()
        self.assertTrue(serve._window_opening())
        self.hold("/api/presence")
        self.assertTrue(self.settle(lambda: not serve._window_opening()))

    def test_the_page_holds_and_never_beats(self):
        page = serve.dashboard_build.render(payload(), live="<b></b>")
        self.assertIn("/api/presence", page)
        self.assertNotIn("/api/alive", page)
        self.assertNotIn("/api/gone", page)
        self.assertNotIn("setInterval(beat", page)
        self.assertIn("/api/preparing", serve.LOADING_PAGE)


class TestSecondTap(unittest.TestCase):
    """Chrome handed --app twice opens two windows. A second tap must not."""

    def setUp(self):
        self.real = (serve._state_at, serve._chrome_wanted,
                     serve._focus_window, serve._open_window)
        self.real_opening = serve.OPENING_FILE
        serve.OPENING_FILE = os.path.join(tempfile.mkdtemp(), "opening.txt")
        self.calls = []
        serve._focus_window = lambda: (self.calls.append("focus"), True)[1]
        serve._open_window = lambda url: (self.calls.append("open"), "chrome-app")[1]
        serve._chrome_wanted = lambda: True

    def tearDown(self):
        (serve._state_at, serve._chrome_wanted,
         serve._focus_window, serve._open_window) = self.real
        shutil.rmtree(os.path.dirname(serve.OPENING_FILE), ignore_errors=True)
        serve.OPENING_FILE = self.real_opening

    def test_an_open_page_is_raised_not_duplicated(self):
        serve._state_at = lambda url: {"page": {"open": True}}
        self.assertEqual(serve._show("http://x/"), "raised")
        self.assertEqual(self.calls, ["focus"])

    def test_no_page_means_a_window_is_opened(self):
        serve._state_at = lambda url: {"page": {"open": False}}
        serve._show("http://x/")
        self.assertEqual(self.calls, ["open"])

    def test_a_server_that_does_not_know_gets_a_window(self):
        # An older server, or one that would not answer, has no "page" key.
        # The old behaviour is the safe one there.
        serve._state_at = lambda url: None
        serve._show("http://x/")
        self.assertEqual(self.calls, ["open"])

    def test_the_default_browser_is_never_raised_by_name(self):
        # `open -a "Google Chrome"` with the page in Arc would raise the wrong
        # app and leave the right one where it was.
        serve._chrome_wanted = lambda: False
        serve._state_at = lambda url: {"page": {"open": True}}
        serve._show("http://x/")
        self.assertEqual(self.calls, ["open"])

    def test_no_chrome_means_nothing_to_raise(self):
        real = serve._chrome_pids
        serve._chrome_pids = lambda: []
        try:
            self.assertFalse(self.real[2]())   # the real _focus_window
        finally:
            serve._chrome_pids = real

    def test_the_raise_never_goes_through_open_or_applescript(self):
        # Both make Chrome a blank window when only the app window is up.
        with open(serve.__file__) as fh:
            source = fh.read()
        self.assertNotIn('"open", "-a"', source)
        self.assertNotIn("osascript", source)

    def test_a_window_still_starting_counts_as_open(self):
        # Chrome starting cold has no page to beat yet. A tap in that gap
        # must not be the second window.
        with open(serve.OPENING_FILE, "w") as fh:
            fh.write(str(time.time() - 2))
        serve._state_at = lambda url: {"page": {"open": False}}
        self.assertEqual(serve._show("http://x/"), "raised")
        with open(serve.OPENING_FILE, "w") as fh:
            fh.write(str(time.time() - serve.OPENING_TTL - 1))
        serve._show("http://x/")
        self.assertEqual(self.calls, ["focus", "open"])

    def test_a_real_open_leaves_the_marker(self):
        real_popen = serve.subprocess.Popen
        serve.subprocess.Popen = lambda cmd, **kw: None
        serve._open_window = self.real[3]
        try:
            serve._open_window("http://x/")
        finally:
            serve.subprocess.Popen = real_popen
        self.assertTrue(serve._window_opening())

    def test_a_raise_that_fails_still_opens_a_window(self):
        serve._focus_window = lambda: (self.calls.append("focus"), False)[1]
        serve._state_at = lambda url: {"page": {"open": True}}
        serve._show("http://x/")
        self.assertEqual(self.calls, ["focus", "open"])

    def test_a_raise_is_read_back_not_believed(self):
        # activateWithOptions: says YES when the request was accepted. Since
        # macOS 14 a request from a process that is not the active app can be
        # accepted and then declined, and the tap then showed nothing at all.
        with open(serve.__file__) as fh:
            source = fh.read()
        activate = source[source.index("def _activate"):source.index("def _focus_window")]
        self.assertIn('b"isActive"', activate)
        self.assertGreater(serve.ACTIVATE_WAIT, 0)

    def test_a_window_that_was_closed_is_opened_not_raised(self):
        # The marker says a window is on its way for twenty seconds. A page
        # that connected in the meantime clears it, so closing that page and
        # tapping again inside the twenty seconds opens a window.
        serve._note_opening()
        serve._clear_opening()             # what a page connecting does
        serve._state_at = lambda url: {"page": {"open": False, "opening": False}}
        serve._show("http://x/")
        self.assertEqual(self.calls, ["open"])


class TestReadiness(CacheIsolated):
    """Ready means the page can be rendered without running the model."""

    def test_nothing_prepared_is_not_ready(self):
        self.assertFalse(serve._payload_ready())

    def test_a_prepared_board_is_ready(self):
        serve.dashboard_build.collect = lambda year: dict.fromkeys(serve.REQUIRED_KEYS, 1)
        serve._payload()
        self.assertTrue(serve._payload_ready())

    def test_a_cache_on_disk_counts_without_the_model_running(self):
        serve.dashboard_build.collect = lambda year: dict.fromkeys(serve.REQUIRED_KEYS, 1)
        serve._payload()
        serve._payload_memo.update(key=None, data=None)  # a fresh process
        self.assertTrue(serve._payload_ready())

    def test_a_warm_runs_once_at_a_time(self):
        # The waiting page polls twice a second. Every poll starting another
        # model run would be the opposite of a fix.
        gate = threading.Event()
        real = serve._warm
        serve._warm = gate.wait
        try:
            self.assertTrue(serve._warm_in_background())
            self.assertFalse(serve._warm_in_background())
        finally:
            gate.set()
            time.sleep(0.1)
            serve._warm = real
        self.assertTrue(serve._warm_lock.acquire(blocking=False))
        serve._warm_lock.release()

    def test_a_warm_that_fails_says_so(self):
        def boom(year):
            raise RuntimeError("no board today")
        serve.dashboard_build.collect = boom
        serve._warm()
        self.assertEqual(serve._warm_state["error"], "no board today")
        serve._warm_state["error"] = None


class TestLoadingPage(Served):
    """A first load after a change used to be ten seconds of blank window,
    which reads as "nothing happened" and earns a second tap."""

    def setUp(self):
        self.real = (serve._payload_ready, serve._warm_in_background, serve._payload)
        self.warms = []
        serve._warm_in_background = lambda: (self.warms.append(1), True)[1]
        serve._warm_state["error"] = None

    def tearDown(self):
        serve._payload_ready, serve._warm_in_background, serve._payload = self.real
        serve._warm_state["error"] = None

    def test_a_board_not_yet_ready_gets_the_waiting_page(self):
        serve._payload_ready = lambda: False
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Preparing the board", body)
        # The token is only ever handed to the real page.
        self.assertNotIn(b"FEP_LIVE", body)
        self.assertEqual(self.warms, [1])

    def test_ready_is_readable_by_the_waiting_page(self):
        serve._payload_ready = lambda: False
        _, body = self.get("/api/ready")
        self.assertFalse(json.loads(body)["ready"])
        serve._payload_ready = lambda: True
        _, body = self.get("/api/ready")
        self.assertTrue(json.loads(body)["ready"])

    def test_a_poll_that_finds_nothing_ready_starts_a_warm(self):
        # The fingerprint can move under a warm (a refresh in a terminal, an
        # edit to fep/), which then memoises the old key. The poll used to
        # only report, so nothing ever started another and the spinner never
        # ended. A warm already under way is not joined: _warm_in_background
        # holds a lock for that, and the stub here stands in for it.
        serve._payload_ready = lambda: False
        self.get("/api/ready")
        self.get("/api/ready")
        self.assertEqual(self.warms, [1, 1])

    def test_a_poll_after_a_failed_warm_does_not_retry_it(self):
        serve._payload_ready = lambda: False
        serve._warm_state["error"] = "no season file"
        _, body = self.get("/api/ready")
        self.assertEqual(json.loads(body)["error"], "no season file")
        self.assertEqual(self.warms, [])

    def test_a_ready_board_is_not_warmed_again(self):
        serve._payload_ready = lambda: True
        self.get("/api/ready")
        self.assertEqual(self.warms, [])

    def test_a_ready_board_gets_the_real_page(self):
        serve._payload_ready = lambda: True
        serve._payload = lambda force=False: payload()
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"FEP_LIVE", body)
        self.assertEqual(self.warms, [])

    def test_a_warm_that_failed_is_not_waited_on_forever(self):
        # The page renders the slow way instead, which raises the same fault
        # where it can be shown, rather than a spinner over a board that will
        # never come.
        serve._payload_ready = lambda: False
        serve._warm_state["error"] = "no season file"

        def boom(force=False):
            raise FileNotFoundError("gone")
        serve._payload = boom
        status, body = self.get("/")
        self.assertEqual(status, 500)
        self.assertEqual(self.warms, [])
        self.assertIsNone(serve._warm_state["error"])

    def test_the_waiting_page_writes_no_dashes(self):
        for dash in ("\u2014", "\u2013"):
            self.assertNotIn(dash, serve.LOADING_PAGE)


class TestTheSheetIsASeparateStep(unittest.TestCase):
    """Run the week stops at git. The page has to say so where the hand is."""

    def test_the_run_button_says_the_sheet_is_separate(self):
        page = serve.dashboard_build.render(payload())
        self.assertIn("Nothing reaches the Sheet", page)

    def test_a_live_page_reports_its_presence(self):
        page = serve.dashboard_build.render(payload(), live="<b></b>")
        self.assertIn("/api/presence", page)

    def test_a_finished_week_offers_the_tables_off_the_servers_record(self):
        page = serve.dashboard_build.render(payload(), live="<b></b>")
        self.assertIn("function paintAfterRun", page)
        self.assertIn("last_run", page)
        self.assertIn('id="ctlAfter"', page)
        # Not a note in the URL: that knew only that an action named `week`
        # had exited 0, and it survived exactly one render.
        self.assertNotIn("after=week", page)
        self.assertNotIn("function afterRun", page)

    def test_the_offer_is_painted_before_the_deployment_gate(self):
        # The button it injects carries data-needs, and the gate only shuts
        # the buttons that exist when it runs.
        page = serve.dashboard_build.render(payload(), live="<b></b>")
        body = page[page.index("function paintState"):]
        self.assertLess(body.index("paintAfterRun();"), body.index("paintHealth();"))

    def test_the_offer_is_painted_off_the_written_flag_not_the_pending_one(self):
        # A replay that recorded nothing used to paint nothing. The offer now
        # stays until a write goes through, and says which of the two happened.
        page = serve.dashboard_build.render(payload(), live="<b></b>")
        painter = page[page.index("function paintAfterRun"):]
        painter = painter[:painter.index("\n}")]
        self.assertIn("sheet_written", painter)
        self.assertIn("this run matched it", painter)
        self.assertIn("Nothing has reached the Sheet", painter)

    def test_a_refused_week_is_offered_as_a_choice(self):
        page = serve.dashboard_build.render(payload(), live="<b></b>")
        follow = page[page.index("function followUp"):]
        follow = follow[:follow.index("\n}")]
        self.assertIn('data-follow="keep-record"', follow)
        self.assertIn('data-follow="week-correction"', follow)
        # The reason is filled in from what happened, and stays editable.
        self.assertIn('id="ctlReason"', follow)
        self.assertIn("ESPN's lines moved after the week was recorded", follow)
        # The refusal's own timestamp is read, with or without one.
        self.assertIn("is already recorded(?: \\(([^)]*)\\))? and this run does not match", follow)

    def test_the_offer_has_its_own_element(self):
        # followUp() owns #ctlFollow and empties it after every action, so an
        # offer placed there vanished the moment Preview was pressed.
        page = serve.dashboard_build.render(payload(), live="<b></b>")
        painter = page[page.index("function paintAfterRun"):]
        painter = painter[:painter.index("\n}")]
        self.assertIn("ctlAfter", painter)
        self.assertNotIn("ctlFollow", painter)


class TestLastRun(Served):
    """The server remembers what its last button press did."""

    def setUp(self):
        self.real = dict(serve.ACTIONS)
        serve._forget_runs()

    def tearDown(self):
        serve.ACTIONS.clear()
        serve.ACTIONS.update(self.real)
        serve._forget_runs()

    def _stub(self, name, ok=True, log=""):
        label, _fn, mutates = self.real[name]
        serve.ACTIONS[name] = (label, lambda payload: serve.Result(
            ok=ok, error=None if ok else "no", log=log), mutates)

    def _run(self, name):
        status, body = self.post("/api/action", {"action": name})
        self.assertEqual(status, 200)
        return body["state"]["last_run"]

    def test_a_week_that_recorded_something_leaves_the_sheet_pending(self):
        self._stub("week", log="2026 FEP | Week 1\n  stat pack ...")
        last = self._run("week")
        self.assertEqual((last["action"], last["status"]), ("week", "created"))
        self.assertTrue(last["sheet_pending"])
        _, body = self.get("/api/state")
        self.assertTrue(json.loads(body)["last_run"]["sheet_pending"])

    def test_a_replay_that_changed_nothing_has_nothing_pending(self):
        # Nothing new to send. The page still offers the tables after it (see
        # test_a_replay_still_offers_the_tables_until_they_are_written): the
        # server cannot tell "nothing new" from "never written".
        self._stub("week", log="2026 FEP | Week 1  (already recorded, unchanged)")
        last = self._run("week")
        self.assertEqual(last["status"], "unchanged")
        self.assertFalse(last["sheet_pending"])
        self.assertFalse(last["sheet_written"])

    def test_the_week_number_is_read_off_the_run(self):
        self._stub("week", log="  espn: game 0 result A -> W\n\n2026 FEP | Week 1\n  stat pack ...")
        self.assertEqual(self._run("week")["week"], 1)
        self._stub("week", log="2026 FEP | Week 10  (bye week)")
        self.assertEqual(self._run("week")["week"], 10)
        self._stub("week", ok=False, log="")
        self.assertIsNone(self._run("week")["week"])

    def test_a_replay_still_offers_the_tables_until_they_are_written(self):
        self._stub("week", log="2026 FEP | Week 1  (already recorded, unchanged)")
        self.assertFalse(self._run("week")["sheet_written"])
        self._stub("cms-live", ok=True)
        last = self._run("cms-live")
        self.assertTrue(last["sheet_written"])
        self.assertFalse(last["sheet_pending"])

    def test_a_correction_and_a_fill_are_named(self):
        self._stub("week", log="2026 FEP | Week 1  (CORRECTED)")
        self.assertEqual(self._run("week")["status"], "corrected")
        self._stub("week", log="2026 FEP | Week 0  (already recorded; leverage filled in)")
        last = self._run("week")
        self.assertEqual(last["status"], "filled")
        self.assertTrue(last["sheet_pending"])

    def test_a_failed_week_is_not_pending(self):
        self._stub("week", ok=False, log="week 1 is already recorded and this run does not match it")
        last = self._run("week")
        self.assertEqual(last["status"], "failed")
        self.assertFalse(last["sheet_pending"])

    def test_writing_the_tables_clears_it(self):
        self._stub("week", log="2026 FEP | Week 1")
        self.assertTrue(self._run("week")["sheet_pending"])
        self._stub("cms-live", ok=False)
        self.assertTrue(self._run("cms-live")["sheet_pending"])
        self._stub("cms-live", ok=True)
        self.assertFalse(self._run("cms-live")["sheet_pending"])

    def test_other_actions_leave_the_record_alone(self):
        self._stub("week", log="2026 FEP | Week 1")
        self._run("week")
        self._stub("board")
        last = self._run("board")
        self.assertEqual(last["action"], "week")
        self.assertTrue(last["sheet_pending"])
