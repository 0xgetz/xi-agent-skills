# CI Workflows — manual activation required

The connected GitHub token does **not** have the `workflow` OAuth scope, so files
under `.github/workflows/` cannot be created via the API (GitHub rejects them with
`does not have the correct permissions to execute CreateCommitOnBranch`).

These workflow definitions are therefore stored here. To activate CI, do ONE of:

**Option A — copy via GitHub web UI (30 seconds)**
1. In the repo, create a new file at `.github/workflows/verify-pro.yml`
2. Paste the contents of [`verify-pro.yml`](verify-pro.yml) from this folder
3. Commit — Actions will run on every push to `pro/`

**Option B — reconnect GitHub with `workflow` scope**
Reconnect the GitHub integration granting the `workflow` scope, then the agent can
push workflow files directly.

What the CI does: installs `pro/requirements.txt` (pinned numpy/scipy) and runs
`pro/verify_system.py`, which exits non-zero if any of the 20 end-to-end checks fail.
A red build means the trading system is genuinely broken.
