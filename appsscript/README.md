# Pushing to the Sheet without Google Cloud

## Why this instead of a service account

Service account key creation is blocked on this account by an organization
policy (`iam.disableServiceAccountKeyCreation`), so the usual route is a dead
end. Organization policies only apply to projects that belong to an
organization, which is why a consumer Gmail project would normally be fine, but
chasing that is not worth it.

An Apps Script web app lives inside the spreadsheet, runs as you, and is not
subject to that policy at all. No Google Cloud project, no key file, nothing to
rotate.

## Setup, once

**1. Add the script.**
In the FEP spreadsheet: **Extensions → Apps Script**. Delete whatever is in
`Code.gs` and paste the contents of `Code.gs` from this folder. Save.

**2. Generate a secret.**

```bash
python3 cli.py token
```

**3. Store the secret in the script.**
In the Apps Script editor: the gear icon (**Project Settings**) → scroll to
**Script Properties** → **Add script property**.
Property `FEP_TOKEN`, value = the token from step 2. Save.

**4. Deploy.**
**Deploy → New deployment** → click the gear next to "Select type" → **Web app**.

| Field | Set to |
|---|---|
| Description | anything, e.g. `fep writer` |
| Execute as | **Me** |
| Who has access | **Anyone with the link** |

Deploy. Google will ask you to authorize it; the "unverified app" warning is
expected for your own script, so click **Advanced → Go to (project name)**.

Copy the **Web app URL**. It ends in `/exec`.

**5. Save the URL and token locally.**
Create `credentials/appsscript.json`:

```json
{
  "url": "https://script.google.com/macros/s/AKfy.../exec",
  "token": "the token from step 2"
}
```

That folder is gitignored.

**6. Point the season file at the right tab.**
In `data/season_2026.json`, set `sheet.tab` to the exact tab name, for example
`"Weighted - MASTER"`. No spreadsheet ID is needed: the script is bound to the
spreadsheet it lives in.

## Test it

Duplicate your tab first (right-click the tab → **Duplicate**, rename it
`Scratch`), then:

```bash
python3 cli.py push --tab="Scratch" --live
```

Compare against the real tab. If it matches, drop the `--tab` flag from then on.

A quick health check without writing anything: open the `/exec` URL in a
browser. It returns JSON listing the tabs and whether `FEP_TOKEN` is set. It
never returns the token itself.

## What this can and cannot do

Even holding both the URL and the token, a caller cannot:

- write outside columns **B..M** (column A holds week labels, column N onward
  holds your placement formulas)
- write to row 1
- write to a tab whose header row does not match the roster
- write anything that is not a number or blank, so a formula string like
  `=SUM(A1)` is rejected

Those checks live in the script, not only in the Python client, because a guard
that only exists on the caller is not a guard.

## If something goes wrong

| Symptom | Cause |
|---|---|
| `Apps Script did not return JSON` and a mention of sign-in | The deployment is not set to "Anyone with the link". Redeploy. |
| `bad token` | `FEP_TOKEN` in Script Properties does not match `credentials/appsscript.json`. |
| `FEP_TOKEN script property is not set` | Step 3 was skipped, or saved on the wrong project. |
| `no tab named ...` | `sheet.tab` does not match the tab name exactly, including spaces and capitals. |
| `header mismatch in column D` | The Sheet's row 1 no longer matches the roster order. This is the guard doing its job. |
| Changes do not appear | Editing the script does not redeploy it. Use **Deploy → Manage deployments → edit → Version: New version**. |

## Rotating the secret

Run `python3 cli.py token` again, update `FEP_TOKEN` in Script Properties and
the token in `credentials/appsscript.json`. No redeploy needed.

If the URL itself leaks, **Deploy → Manage deployments → Archive**, then create
a new deployment and update the URL.
