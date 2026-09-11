# FEP 2026

The Family Eagles Pool simulator. `README.md` explains what it does; this file
is the short list of things that are easy to get wrong.

Two skills carry the detail. Read the relevant one before working:

- **`fep-dev`** -- editing, testing, committing, pushing. Read it before
  touching a file.
- **`fep-week`** -- the weekly run, and publishing to the Sheet and the CMS.

## The five that cost an hour each

1. **One repo, one branch.** `2026/` on `main`. If `git worktree list` shows
   more than one line or `git branch` shows more than `main`, that is an
   unmerged fork, not a workspace. Resolve it before writing code.

2. **`dashboard/index.html` is generated.** Edit `dashboard/template.html` and
   rebuild. The generated file is gitignored and overwritten every build.
   The same template is both the app and the offline viewer: served by
   `dashboard/serve.py` its buttons run `cli.py`, opened as a file they copy
   commands. If the buttons look dead, the page was opened from Finder rather
   than through `scripts/FEP.app`.

3. **The repo is self-contained; keep it that way.** History lives in
   `data/history/`, the 2025 regression baseline in `tests/fixtures/`. All of
   it used to be read from outside and it failed silently. If you find yourself
   writing a path with `..` or `~/Library` in it, that is the bug.

4. **Run the whole suite, not the file you touched.** The count moves, so do
   not memorise one; the runner finds every file itself:
   ```bash
   python3 -m pytest tests -q && node appsscript/test_code.js
   ```
   `test_engine.py` is the biggest by some way. `test_review_fixes.py` and
   `test_serve.py` hold the regressions from external reviews, each pinned to
   one finding, and `test_fixture.py` is the one that catches
   `dashboard/sample-data.json` going stale.

5. **Pushing needs the personal GitHub account.** This machine's active `gh`
   account is the work one, so a plain `git push` 403s. Use
   `scripts/fep-push.command`. Never `gh auth switch` -- it breaks work repos.

## Invariants worth protecting

- `data/season_2026.json` is the only thing here that cannot be regenerated.
- **Facts are stored, statistics are not.** Never cache a computed number in the
  season file; it will silently disagree with the board after a correction.
- **Snapshots freeze.** A row published in week N is identical in week N+1.
  Enforced, not just asserted: an identical replay is a no-op, a changed one is
  refused by name, and a rewrite needs `--correction "why"`, which is recorded
  on the entry. Chart files in `chart-data/` get the same rule. This is the
  contract `FROZEN_TABS` enforces in `Code.gs`; both halves keep it.
- **A run that changed nothing leaves no trace.** `save()` ignores the
  bookkeeping timestamps when deciding whether to write, so re-running a week
  does not produce a commit that only moves `updated_at`.
- **Deployment readiness is asked, never inferred.** A config file existing on
  this laptop says nothing about what Google is running. Press "Check the
  deployments", or `sheets.deployment_health()`. There is one deployment,
  `cms_url` -- see `docs/CMS.md`.
- **The CMS tables are the only thing that leaves this machine for a
  spreadsheet.** The `Weighted - MASTER` push was retired in September 2026
  along with the service-account transport, because nothing read that tab any
  more, and its `B2:M20` op came out of `Code.gs` on 2026-09-10 (CODE_VERSION
  `2026.09.10-a`): `writeTable` is the only op the deployment accepts.
- Standard library only, system Python 3.9.
- No em dashes or en dashes in generated prose. Write `--`. There is a test.

## Working with a human in the loop

If `git status` shows changes you did not make, another session is active. Ask
before committing them -- a diff does not tell you finished work from work in
progress. Stage your own paths, never `git add -A`.
