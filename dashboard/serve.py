#!/usr/bin/env python3
"""The dashboard, served as an application rather than opened as a file.

A page opened from the filesystem has no origin: it cannot reach the season
file, run the model or talk to the Sheet, which is why every button in the
built `index.html` could only copy a shell command for you to run yourself.
Served from here the same page gets an origin, and each of those buttons
performs the thing instead.

Nothing new is implemented here. Every action is a call into `cli.py`, run in
this process with its output captured and handed back to the page, so the
button and the command cannot drift apart: there is still exactly one
implementation of the weekly run.

    python3 dashboard/serve.py

or double-click `scripts/FEP.app`, which is the same thing with an icon.
"""

from __future__ import annotations

import contextlib
import glob
import hashlib
import importlib.util
import io
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import cli  # noqa: E402  (needs ROOT on the path first)
from fep import (espn, engine, history, manifest,  # noqa: E402
                 season as season_mod, sheets)

YEAR = cli.YEAR
DEFAULT_PORT = int(os.environ.get("FEP_PORT", "8765"))

# The personal account the remote expects. A plain push authenticates as the
# machine's active (work) account and is refused, so the token is fetched from
# gh at push time and never stored. See the fep-dev skill.
GH_USER = "jleibowitz9"

# Only the run's own outputs are ever staged. Anything half-finished elsewhere
# in the tree belongs to whoever is working on it.
BACKUP_PATHS = ["data", "newsletters", "chart-data"]


def _load_build():
    """`build.py` sits next to this file and is too generic a name to import."""
    spec = importlib.util.spec_from_file_location(
        "dashboard_build", os.path.join(HERE, "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dashboard_build = _load_build()

# One season file, one model, one process. Two clicks arriving together would
# otherwise interleave a refresh and a snapshot, and the season file is the one
# thing in this repo that cannot be regenerated.
_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# the payload, which is expensive and rarely different

CACHE_DIR = os.path.join(ROOT, "data", "dashboard_cache")
CACHE_FILE = os.path.join(CACHE_DIR, "payload.json")

# Where the running server says it can be reached. The port is not reliably the
# default one, so nothing may assume it: the launcher polls this to know when
# the app is up, and a second tap of the icon reads it to find the server that
# is already running rather than starting a second one beside it.
URL_FILE = os.path.join(CACHE_DIR, "url.txt")

_payload_lock = threading.Lock()
_payload_memo = {"key": None, "data": None}


def _fingerprint():
    """Everything the payload is a function of.

    collect() costs about eleven seconds, nearly all of it precomputing a
    counterfactual board for every remaining game twice over: once for What If
    and once for the leverage ranking. That work is completely determined by
    the season file and by the code that reads it, so it can be cached, but
    only against a key that moves when either of those does. Editing
    fep/analytics.py and getting yesterday's numbers back would be a far worse
    bug than the wait it saves.
    """
    parts = []
    watched = [season_mod.path_for(YEAR), os.path.join(HERE, "build.py")]
    watched += sorted(glob.glob(os.path.join(ROOT, "fep", "*.py")))
    watched += sorted(glob.glob(os.path.join(ROOT, "data", "history", "*")))
    for path in watched:
        try:
            stat = os.stat(path)
            parts.append("{}:{}:{}".format(path, stat.st_mtime_ns, stat.st_size))
        except OSError:
            parts.append(path + ":missing")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# The keys the page cannot be rendered without. A cache file is the one input
# here that nothing validates on the way in: it can be truncated by a crash,
# left behind by an older version of collect(), or simply be a file with the
# right name and the wrong contents. Rendering from one of those took the whole
# server down with an empty reply, which reads as "the app is broken" rather
# than "ignore that file". tests/test_serve.py asserts collect() still produces
# all of these, so the guard cannot fall out of step with the real payload.
REQUIRED_KEYS = frozenset((
    "year", "week", "games", "roster", "colors", "picks", "board",
    "snapshots", "ranked", "whatif",
))


def _read_cache(key):
    try:
        with open(CACHE_FILE) as fh:
            blob = json.load(fh)
    except (OSError, ValueError):
        return None
    if blob.get("fingerprint") != key:
        return None
    data = blob.get("data")
    if not isinstance(data, dict) or not REQUIRED_KEYS.issubset(data):
        return None
    return data


def _write_cache(key, data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        temporary = CACHE_FILE + ".tmp"
        with open(temporary, "w") as fh:
            json.dump({"fingerprint": key, "data": data}, fh)
        # Atomic, so a cache half-written when the app is quit is never read
        # back as a whole one.
        os.replace(temporary, CACHE_FILE)
    except OSError:
        pass  # a cache that cannot be written is a slow app, not a broken one


def _payload(force=False):
    """The dashboard payload, computed at most once per change.

    The lock is held across the computation rather than around the lookup, so
    two page loads arriving together produce one model run and the second waits
    for the first rather than starting its own.
    """
    key = _fingerprint()
    with _payload_lock:
        if not force:
            if _payload_memo["key"] == key:
                return _payload_memo["data"]
            cached = _read_cache(key)
            if cached is not None:
                _payload_memo.update(key=key, data=cached)
                return cached
        data = dashboard_build.collect(YEAR)
        _payload_memo.update(key=key, data=data)
    _write_cache(key, data)
    return data


# --------------------------------------------------------------------------
# running a command


class Result(dict):
    """What an action returns to the page: did it work, and what did it say."""


def _capture(fn, argv):
    """Run one cli.py command, and collect what it printed either way.

    cli.py reports every expected failure with `sys.exit("a sentence")`, so a
    SystemExit carrying a string is not a crash, it is the error message the
    terminal would have shown. Anything else is a real fault and gets its
    traceback into the log, where it is visible rather than lost to a console
    nobody is watching.
    """
    buffer = io.StringIO()
    ok, error = True, None
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            fn(argv)
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, str):
            ok, error = False, code
        elif code not in (0, None):
            ok, error = False, "Stopped with status {}.".format(code)
    except (engine.SeasonError, sheets.SheetError, espn.ESPNError,
            history.HistoryError) as exc:
        ok, error = False, str(exc)
    except Exception as exc:  # noqa: BLE001  a fault must still reach the page
        ok, error = False, "{}: {}".format(type(exc).__name__, exc)
        buffer.write("\n" + traceback.format_exc())
    return Result(ok=ok, error=error, log=buffer.getvalue().rstrip())


def _command(name, argv=()):
    """An action that is one cli.py command and nothing else."""
    return lambda payload: _capture(cli.COMMANDS[name], list(argv))


def _git(*args):
    done = subprocess.run(["git"] + list(args), cwd=ROOT,
                          capture_output=True, text=True)
    return done.returncode, (done.stdout + done.stderr).strip()


def _backup_paths():
    """The files to archive: the run's own, or the directories as a fallback.

    A manifest names exactly what the last run wrote. Without one -- a run from
    before manifests existed, or a bare "Save to git" press with no run behind
    it -- fall back to the directories, which is the old behaviour and still
    better than nothing.
    """
    recorded = manifest.read()
    if recorded and recorded["paths"]:
        return recorded["paths"]
    return list(BACKUP_PATHS)


def _backup(payload=None):
    """Commit the run's outputs and send them to GitHub.

    This is what `scripts/fep-week.command` has always done after a run. It is
    here so that finishing a week from the page leaves the same trail as
    finishing one from the terminal, rather than a season file that only exists
    on this laptop.

    EVERY STEP IS CHECKED
    ---------------------
    This used to discard the result of `git add` and treat a failed `git commit`
    as merely something to log. With nothing then waiting ahead of origin/main,
    the next branch reported "GitHub is already up to date" and returned
    success -- so an index lock, or a full disk, read on the page as a finished,
    archived week. A backup that cannot say truthfully whether it worked is
    worse than no backup, because it stops you checking.
    """
    log = []
    paths = _backup_paths()
    code, dirty = _git("status", "--porcelain", *paths)
    if code != 0:
        return Result(ok=False, error="git could not read the tree.", log=dirty)

    if dirty.strip():
        code, out = _git("add", *paths)
        if code != 0:
            log.append(out)
            return Result(ok=False, error="git could not stage the run.",
                          log="\n".join(log))
        code, out = _git("commit", "-q", "-m",
                         "The weekly run, {}".format(time.strftime("%Y-%m-%d")))
        if code != 0:
            log.append(out)
            log.append("Nothing was committed, so nothing was pushed.")
            return Result(ok=False, error="git could not commit the run.",
                          log="\n".join(log))
        log.append("Committed {} path(s).".format(len(paths)))
    else:
        log.append("Nothing new to commit.")

    code, ahead = _git("log", "origin/main..HEAD", "--oneline")
    if code != 0:
        # Cannot see origin/main, so cannot know whether anything is waiting.
        # Saying "up to date" here would be the same lie in a quieter place.
        log.append(ahead)
        return Result(ok=False, error="git could not compare against GitHub.",
                      log="\n".join(log))
    if not ahead.strip():
        log.append("GitHub is already up to date.")
        return Result(ok=True, error=None, log="\n".join(log))

    count = len(ahead.strip().splitlines())
    token = subprocess.run(["gh", "auth", "token", "--user", GH_USER],
                           capture_output=True, text=True)
    if token.returncode != 0 or not token.stdout.strip():
        log.append("{} commit(s) are waiting, but there is no token for {}.".format(
            count, GH_USER))
        log.append("The commits are safe locally. Run: gh auth login --user " + GH_USER)
        return Result(ok=False, error="Could not authenticate the push.",
                      log="\n".join(log))

    pushed = subprocess.run(["git", "push", "-q", "origin", "main"], cwd=ROOT,
                            capture_output=True, text=True,
                            env=dict(os.environ, GH_TOKEN=token.stdout.strip()))
    if pushed.returncode == 0:
        log.append("Pushed {} commit(s) to GitHub.".format(count))
        return Result(ok=True, error=None, log="\n".join(log))
    log.append((pushed.stdout + pushed.stderr).strip())
    log.append("The commits are safe locally.")
    return Result(ok=False, error="The push was refused.", log="\n".join(log))


# The last deployment check, and how long it stays worth believing. A
# deployment does not change under you often, but it changes exactly when
# someone redeploys it, which is precisely when this is being watched.
_health_memo = {"at": 0.0, "data": None}
HEALTH_TTL = 300.0


def _health_state():
    """The cached deployment check, in the shape the page renders."""
    data = _health_memo["data"]
    if not data or (time.time() - _health_memo["at"]) > HEALTH_TTL:
        return {"checked": False, "deployments": []}
    return {"checked": True, "deployments": data,
            "checked_age": int(time.time() - _health_memo["at"])}


def _health(payload=None):
    """Ask both deployments what they are actually running.

    Its own button rather than something the page does on load, because it is
    two network calls to Google and either can be slow to wake.
    """
    def work(argv):
        rows = sheets.deployment_health()
        _health_memo.update(at=time.time(), data=rows)
        for row in rows:
            if not row["configured"]:
                print("  {:7} not configured".format(row["name"]))
            elif not row["reachable"]:
                print("  {:7} did not answer -- {}".format(row["name"], row["error"]))
            elif row["current"]:
                print("  {:7} running {}".format(row["name"], row["version"]))
            else:
                print("  {:7} running {}, this checkout is {}".format(
                    row["name"],
                    row["version"] or "an older version (no version stamp)",
                    row["local"]))
        stale = [r["name"] for r in rows if r["configured"] and not r["current"]]
        if stale:
            print("\n  {} {} redeploying. Editing Code.gs does not deploy it:".format(
                " and ".join(stale), "needs" if len(stale) == 1 else "need"))
            print("  paste appsscript/Code.gs into the editor, save, then")
            print("  Deploy > Manage deployments > edit > Version: New version.")
    return _capture(work, [])


def _rebuild(payload=None):
    """Write the offline copy, from the payload the served page will use.

    cli.py's `dashboard` command collects and builds in one step, which would
    mean computing the payload here and then computing an identical one again
    for the cache. Doing the two halves in order instead means one model run
    serves both the file on disk and the next page load.
    """
    def work(argv):
        data = _payload(force=True)
        path = dashboard_build.build(data)
        print("Built {} ({:.0f} KB)".format(
            os.path.relpath(path, ROOT), os.path.getsize(path) / 1024))
    return _capture(work, [])


def _week(payload):
    """The whole week: run the model, rebuild the file copy, archive it.

    Three steps rather than one button per step, because they are not really
    separable. A run that is not written to disk and not committed is a run you
    have to remember to finish.
    """
    argv = [str(payload["week"])] if payload.get("week") not in (None, "") else []
    steps = [("The weekly run", lambda: _capture(cli.COMMANDS["week"], argv)),
             ("Rebuilding the offline copy", _rebuild),
             ("Saving to git", lambda: _backup())]
    log, ok, error = [], True, None
    for title, step in steps:
        result = step()
        log.append("--- {} ---".format(title))
        if result["log"]:
            log.append(result["log"])
        if not result["ok"]:
            ok, error = False, result["error"]
            # A failed model run must not be followed by a commit of whatever
            # half-written state it left behind.
            log.append("Stopped here. The steps after this did not run.")
            break
        log.append("")
    return Result(ok=ok, error=error, log="\n".join(log).rstrip())


def _picks(payload):
    """Load a pick sheet that was dropped onto the page.

    The CSV arrives as text rather than as an upload so that the server needs
    no multipart parsing, and it is written beside the season file only for as
    long as cli.py takes to read it.
    """
    text = payload.get("csv") or ""
    if not text.strip():
        return Result(ok=False, error="That file was empty.", log="")
    scratch = os.path.join(ROOT, "data", ".picks-upload.csv")
    try:
        with open(scratch, "w") as fh:
            fh.write(text)
        argv = [scratch] + (["--force"] if payload.get("force") else [])
        result = _capture(cli.COMMANDS["picks"], argv)
        if not result["ok"] and result["error"].startswith(("ValueError", "IndexError",
                                                            "KeyError")):
            result["error"] = ("That file is not a pick sheet this can read. "
                               "It wants one row per competitor: a name, a W or L "
                               "for each game, then a points guess.")
        return result
    finally:
        if os.path.exists(scratch):
            os.remove(scratch)


ACTIONS = {
    # name: (what the page calls it, the callable, does it change anything)
    "week": ("Run the week", _week, True),
    "refresh": ("Refresh from ESPN", _command("refresh"), True),
    "rebuild": ("Rebuild the offline copy", _rebuild, False),
    "cms-preview": ("Preview the CMS tables", _command("cms"), False),
    "cms-live": ("Write the CMS tables", _command("cms", ["--live"]), True),
    "cms-csv": ("Export the CMS tables", _command("cms", ["--csv"]), False),
    "health": ("Check the deployments", _health, False),
    "backup": ("Save to git", _backup, True),
    "picks": ("Load a pick sheet", _picks, True),
    "board": ("Run the model", _command("board"), False),
    "leverage": ("Rank the remaining games", _command("leverage"), False),
}

# Writing to the Sheet or to the CMS reaches outside this machine, so the page
# asks first and names what it is about to touch.
CONFIRM = {"cms-live"}

# The actions that change what the board is drawn from. The page reloads after
# these, so the new payload is computed before the response goes back rather
# than during the reload, where it would look like the app had hung.
REWARM = {"week", "refresh", "picks"}


# --------------------------------------------------------------------------
# what the page needs to know about the world


def _state():
    """Everything the control room shows that is not in the payload."""
    state = {"year": YEAR, "root": ROOT}
    try:
        season = season_mod.load(YEAR)
    except FileNotFoundError:
        state["season"] = None
        return state

    outstanding = [n for n in season["roster"] if not season["picks"].get(n)]
    next_week = season_mod.week_to_run(season)
    state["season"] = {
        "week": season_mod.current_nfl_week(season),
        # What "Run the week" will actually do, named rather than assumed. The
        # two differ during a bye, and that difference is precisely the one a
        # button reading only "Run the week" would hide.
        "next_week": next_week,
        "next_is_bye": season_mod.is_bye_week(season, next_week),
        "played": season_mod.games_played(season),
        "roster": len(season["roster"]),
        "outstanding": outstanding,
        "ready": season_mod.has_picks(season),
    }
    state["sheet"] = {
        "configured": sheets.appsscript_available(),
        # Deliberately whatever the last check found, never a fresh probe: a
        # page load must not wait on two round trips to Google. Absent means
        # "not checked", which the page says in those words -- the old
        # behaviour was to read a file existing on disk as "Apps Script ready",
        # which is a claim about this laptop dressed up as one about Google.
        **_health_state(),
    }
    code, dirty = _git("status", "--porcelain", *_backup_paths())
    ahead_code, ahead = _git("log", "origin/main..HEAD", "--oneline")
    state["git"] = {
        "dirty": len([l for l in dirty.splitlines() if l.strip()]) if code == 0 else 0,
        "ahead": len([l for l in ahead.splitlines() if l.strip()]) if ahead_code == 0 else 0,
    }
    return state


# --------------------------------------------------------------------------
# the server


class Handler(BaseHTTPRequestHandler):
    server_version = "FEP"
    token = ""

    # The default logger writes a line per request to stderr, which buries the
    # output of the run itself in the log the launcher writes.
    def log_message(self, fmt, *args):
        pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            # A reload or a navigation away mid-response. The page weighs 135 KB
            # and takes long enough to send that this is routine, and a
            # traceback in the log for it would make a real fault harder to
            # find rather than easier.
            self.close_connection = True

    # -- helpers ----------------------------------------------------------

    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Every response is this season's live state, so none of it may be
        # remembered by the browser: a cached page would quietly show last
        # week's board after a run.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload))

    def _local_host(self):
        """Refuse a request addressed to anything but this machine.

        The token is the real guard and it is a good one: a custom header with
        no CORS headers and no OPTIONS route cannot be forged cross-origin. But
        `GET /` is unauthenticated and renders the token into the page, and a
        page served from a name that resolves to 127.0.0.1 is same-origin with
        this server as far as the browser is concerned -- so it could read the
        token out and then drive the actions that write to Google.

        Binding to 127.0.0.1 stops the network. This stops the name.
        """
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1", "")

    def _authorised(self):
        """Guard the actions against every other page in the browser.

        A local server is reachable by any site the browser happens to have
        open, and one of these routes writes to a real Google Sheet. The token
        is minted per launch and only ever handed to the page this server
        itself rendered, so a request without it did not come from the app.
        """
        if self.headers.get("X-FEP-Token", "") != self.token:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in self._origins():
            return False
        return True

    def _origins(self):
        host, port = self.server.server_address[0], self.server.server_address[1]
        return {"http://127.0.0.1:{}".format(port),
                "http://localhost:{}".format(port),
                "http://{}:{}".format(host, port)}

    # -- routes -----------------------------------------------------------

    def do_GET(self):  # noqa: N802  (the base class names it)
        if not self._local_host():
            return self._send(421, "Not this server.", "text/plain; charset=utf-8")
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._page()
        if path == "/api/state":
            return self._json(200, _state())
        if path.startswith("/assets/"):
            return self._asset(path)
        self._send(404, "Not found.", "text/plain; charset=utf-8")

    def do_POST(self):  # noqa: N802
        if not self._local_host():
            return self._send(421, "Not this server.", "text/plain; charset=utf-8")
        path = self.path.split("?", 1)[0]
        if not self._authorised():
            return self._json(403, {"ok": False, "error": "This request did not "
                                    "come from the dashboard."})
        if path == "/api/quit":
            self._json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path != "/api/action":
            return self._send(404, "Not found.", "text/plain; charset=utf-8")

        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            return self._json(400, {"ok": False, "error": "Unreadable request."})

        name = payload.get("action")
        if name not in ACTIONS:
            return self._json(400, {"ok": False,
                                    "error": "No such action: {}".format(name)})
        label, fn, _mutates = ACTIONS[name]

        # Serialised rather than queued. If something is already running the
        # honest answer is to say so, not to hold the click and replay it after
        # the state it was clicked against has changed.
        if not _LOCK.acquire(blocking=False):
            return self._json(409, {"ok": False,
                                    "error": "Something else is still running."})
        started = time.time()
        try:
            result = fn(payload)
        finally:
            _LOCK.release()
        # The page is about to reload for these, so the payload is built now,
        # inside the spinner the click already put up. _payload() recomputes
        # only if the season file actually moved, so the weekly run (which
        # rebuilt it as one of its own steps) pays nothing here.
        if result["ok"] and name in REWARM:
            try:
                _payload()
            except Exception:  # noqa: BLE001  a warm failure is not a failed action
                pass
        result["action"] = name
        result["label"] = label
        result["seconds"] = round(time.time() - started, 2)
        result["state"] = _state()
        self._json(200, result)

    # -- the page ---------------------------------------------------------

    def _page(self):
        """Render from the season file on every load.

        The built `index.html` bakes its data in and needs rebuilding to change.
        Rendering here instead means a reload is all it takes to see a run, and
        `index.html` goes back to being what it is for: the copy that still
        works when nothing is running.
        """
        live = ('<script>window.FEP_LIVE={"token":%s};</script>'
                % json.dumps(self.token))
        try:
            data = _payload()
            page = dashboard_build.render(data, live=live)
        except FileNotFoundError:
            return self._send(500, "No season file for {}.".format(YEAR),
                              "text/plain; charset=utf-8")
        except Exception:  # noqa: BLE001
            # Whatever went wrong, saying so beats dropping the connection: an
            # empty reply looks like the app never started.
            traceback.print_exc()
            return self._send(500, "The page could not be built.\n\n"
                              + traceback.format_exc(),
                              "text/plain; charset=utf-8")
        self._send(200, page, "text/html; charset=utf-8")

    def _asset(self, path):
        """Static files, from the assets folder and nowhere else."""
        rel = os.path.normpath(path.lstrip("/")).replace("\\", "/")
        full = os.path.join(HERE, rel)
        # normpath resolves any ".." before this check, so a path that has
        # climbed out of the folder cannot pass it.
        if not full.startswith(os.path.join(HERE, "assets") + os.sep) \
                or not os.path.isfile(full):
            return self._send(404, "Not found.", "text/plain; charset=utf-8")
        types = {".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
                 ".ico": "image/x-icon", ".webp": "image/webp"}
        kind = types.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        with open(full, "rb") as fh:
            self._send(200, fh.read(), kind)


def _answers(url):
    """An FEP server at this URL, as opposed to something else or nothing."""
    try:
        request = urllib.request.Request(url.rstrip("/") + "/api/state")
        with urllib.request.urlopen(request, timeout=1) as response:
            return response.headers.get("Server", "").startswith("FEP")
    except Exception:  # noqa: BLE001  anything at all means "not ours"
        return False


def _running_url(port):
    """The URL of a server that is already up, or None.

    Checked against the file the running server wrote rather than against the
    default port, because the port it actually got is not always the one it
    asked for. Missing that made a second tap of the icon start a second server
    on the next port up, and made the launcher report a failure while the app
    was running perfectly well one port over.
    """
    for url in (_recorded_url(), "http://127.0.0.1:{}/".format(port)):
        if url and _answers(url):
            return url
    return None


# Chrome's --app mode is the only reliably chrome-less window on this machine.
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _open_window(url):
    """Show the dashboard in a window that looks like an application.

    Handing the URL to the default browser put the page inside Arc's localhost
    developer toolbar, which makes it a browser looking at a page rather than
    an app. --app gives a plain window: no tab strip, no address bar, no
    developer chrome, and its own entry in the window list.

    Launching the binary while Chrome is already running hands the flag to the
    existing instance, which opens the app window there. `open -na` would not:
    the second instance finds the first holding the profile and drops its
    arguments on the way past.

    FEP_BROWSER=default turns the whole preference off, and a machine without
    Chrome never sees it in the first place.
    """
    if os.environ.get("FEP_BROWSER") != "default" and os.path.exists(CHROME):
        try:
            subprocess.Popen([CHROME, "--app=" + url, "--window-size=1440,900"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "chrome-app"
        except OSError:
            pass
    webbrowser.open(url)
    return "default-browser"


def _write_url(url):
    """Record where this server is, and which process is answering there.

    The pid matters as much as the url. A server killed with SIGTERM does not
    run its cleanup, so this file outlives it, and a stale one pointing at a
    port something else has since taken would have the next launch decide the
    app was already open and exit without starting anything.
    """
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(URL_FILE, "w") as fh:
            fh.write("{}\n{}".format(os.getpid(), url))
    except OSError:
        pass  # the launcher falls back to the default port


def _recorded_url():
    """The url from that file, if the process that wrote it is still alive."""
    try:
        with open(URL_FILE) as fh:
            pid, url = fh.read().strip().split("\n", 1)
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return None
    return url.strip()


def _clear_url():
    try:
        os.remove(URL_FILE)
    except OSError:
        pass


def _warm():
    try:
        _payload()
    except Exception as exc:  # noqa: BLE001  the page will report it properly
        print("Could not prepare the board: {}".format(exc), flush=True)


def _free_port(preferred):
    """The chosen port, or the next one that is not taken.

    A crashed launcher can leave the old port held for a minute, and refusing
    to start over something that transient is not worth the support call.
    """
    for port in range(preferred, preferred + 12):
        with socket.socket() as probe:
            # The same option the server itself sets. Without it a port left in
            # TIME_WAIT by the previous run looks taken, the app quietly moves
            # to the next one, and everything that expected it on the usual
            # port stops finding it.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port between {} and {}.".format(
        preferred, preferred + 11))


def serve(port=DEFAULT_PORT, open_browser=True):
    running = _running_url(port)
    if running:
        # A server on its way out still answers for a moment. Looking once meant
        # a launch that landed during a shutdown handed the window to a server
        # about to stop and exited without starting one, so the tap produced
        # nothing at all. Look twice, a beat apart, and start one if the first
        # answer does not hold.
        time.sleep(0.35)
        if _answers(running):
            print("Already open at {}".format(running), flush=True)
            if open_browser:
                _open_window(running)
            return

    Handler.token = secrets.token_urlsafe(24)
    port = _free_port(port)
    # 127.0.0.1, never 0.0.0.0: this is one person's laptop, and the server can
    # write to a Google Sheet. It has no business being reachable from the
    # coffee shop's network.
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:{}/".format(port)
    _write_url(url)
    print("FEP {}".format(YEAR))
    print(url)
    print("\nLeave this window open while you use it. Ctrl-C, or Quit in the")
    print("page, closes the app.\n", flush=True)
    # Built before the browser asks for it where possible, so the first page
    # load is a read rather than eleven seconds of model runs. It is only ever
    # that slow when the season file has changed since the last time.
    threading.Thread(target=_warm, daemon=True).start()
    if open_browser:
        threading.Timer(0.4, _open_window, args=(url,)).start()
    # Quit from the page, a kill, and Ctrl-C all have to clear the url file, or
    # the next launch reads it and believes a dead server is still answering.
    def stop(signum, frame):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    for received in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(received, stop)
        except ValueError:
            pass  # not the main thread, which only happens under the tests

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        _clear_url()
        print("Closed.", flush=True)


if __name__ == "__main__":
    serve(open_browser="--no-open" not in sys.argv)
