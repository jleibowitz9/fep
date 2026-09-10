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

3. **History reads from outside the repo.** `fep/history.py` needs `2022/`
   through `2025/` as *siblings* of this folder, plus the `fep-master` skill's
   data dir (`FEP_DATA_DIR`). A worktree created anywhere else silently loses
   seasons and fails as six confusing test errors, not as a missing file.

4. **There are four test files, 191 tests.** `test_engine.py` is a third of the
   suite. Run all of them:
   ```bash
   for t in test_engine test_review_fixes test_cms test_backfill; do python3 tests/$t.py; done
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
