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
  "cms_url": "https://script.google.com/macros/s/AKfy.../exec",
  "cms_token": "the token from step 2"
}
```

That folder is gitignored.

A file that also carries `url` and `token` is fine. They addressed a second,
legacy deployment that was retired in September 2026, and nothing reads them.

**6. Nothing to point at.**
`writeTable` creates each of the seven table tabs if it is missing, and refuses
any tab outside that list. No spreadsheet ID is needed either: the script is
bound to the spreadsheet it lives in.

## Test it

A dry run reaches nothing outside this machine and prints every table it would
write:

```bash
python3 cli.py cms
```

When that looks right, `python3 cli.py cms --live` writes it. A first write to
an empty tab is all inserts; after that the frozen tables refuse any row that
has changed, so a mistake is caught rather than absorbed.

A quick health check without writing anything: open the `/exec` URL in a
browser. It returns JSON with the `CODE_VERSION` it is running and whether
`FEP_TOKEN` is set. It never returns the token, and since `2026.09.10-a` it no
longer lists the spreadsheet's tabs either: the URL is reachable by anyone who
has it, and the health check only needs to answer whether this checkout is what
Google is running.

## What this can and cannot do

The script does one thing: upsert one of the seven CMS tables by slug. Even
holding both the URL and the token, a caller cannot:

- ask for any other op. The `B2:M20` writer that once fed `Weighted - MASTER`
  was removed in `2026.09.10-a`, and a request for it is refused
- write to a tab outside the seven tables
- send a row belonging to a season other than the one named in the push
- move a row in a frozen table (`weeks`, `standings`, `picks`) without
  `allowCorrection`, which names every row it changes in the response
- write a string that could be read as a formula, so `=SUM(A1)` is rejected
- write under a header that does not match the columns it sent. Appending
  columns is allowed; renaming, reordering or dropping one is refused
- delete a row, ever

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
