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

4. **There are five test files, 230 tests.** `test_engine.py` is a third of the
   suite. Run all of them:
   ```bash
   for t in test_engine test_review_fixes test_cms test_backfill test_serve; do python3 tests/$t.py; done
   ```

5. **Pushing needs the personal GitHub account.** This machine's active `gh`
   account is the work one, so a plain `git push` 403s. Use
   `scripts/fep-push.command`. Never `gh auth switch` -- it breaks work repos.

## Invariants worth protecting

- `data/season_2026.json` is the only thing here that cannot be regenerated.
- **Facts are stored, statistics are not.** Never cache a computed number in the
  season file; it will silently disagree with the board after a correction.
- **Snapshots freeze.** A row published in week N is identical in week N+1.
  `tests/test_cms.py` asserts this.
- The Sheet push touches `B2:M20` and nothing else. Both guards, Python and
  Apps Script, stay.
- Standard library only, system Python 3.9.
- No em dashes or en dashes in generated prose. Write `--`. There is a test.

## Working with a human in the loop

If `git status` shows changes you did not make, another session is active. Ask
before committing them -- a diff does not tell you finished work from work in
progress. Stage your own paths, never `git add -A`.
