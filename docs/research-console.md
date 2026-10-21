# Research console

The console is part of SAGE, uses the existing autonomous runner and reads its
run directories. It has no database and does not edit scientific artifacts.
The supported remote deployment is loopback HTTP on AutoDL plus an SSH tunnel.

On AutoDL, in the same configured environment used for `sage autonomous`:

```bash
cd /root/autodl-tmp/Awesome-AutoResaerch
.venv/bin/python -m sage console --port 8765 --allow-live
```

Omit `--allow-live` for read-only viewing. The command prints an access URL with
a generated platform token (not the provider API key). For persistent service
deployments set a private `SAGE_CONSOLE_TOKEN` of at least 32 characters. Never
commit either credential. Model configuration remains in the server environment.

On your own computer:

```bash
ssh -N -L 8765:127.0.0.1:8765 -p 12066 root@connect.westb.seetacloud.com
```

Open the printed `http://127.0.0.1:8765/#token=...` URL. The page removes the token
from the address bar and stores it in that browser tab's session storage. API
requests require the token and reject foreign origins/hostnames. The server
listens only on loopback. This is a single-owner console, not a public multi-user
service. Do not expose it directly to the internet.

Enter a topic and review finite budgets before starting. The UI requires explicit
live-call consent, launches the existing CLI, saves the real process exit code,
and refuses to start another active autonomous launcher. Scientific API keys are
never accepted by or transmitted to the browser. A browser disconnect does not
cancel the research. Current starts retain default 4 researchers, 2 discussion
rounds, 4 formal attempts, 640 research-tool attempts, and 7200 seconds; these
are not a currency or token-spend cap.

Views: full input; evidence cards and source spans; all initial candidates and
synthesis versions; peer reviews, audited advice and revisions; advisory reviews
and formal grading; safe tool events with correlation IDs and hashes; exact-byte
artifact downloads. The stage bar shows the latest observed stage, not a percent
complete. The event view is explicitly a recent 200-event tail. Complete logs
remain on disk. Missing, malformed or pending snapshots are not called success.
Team synthesis completion is distinct from completed formal grading/export.

This entry point produces conjectures and experiment protocols. It does not
implement the general experiment-to-paper bridge. Same-family model reviews are
advisory and do not establish independent scientific acceptance.

## Review integrity update

Scientific projection v2 preserves candidate `calibration_plan` and the typed
`shared_scientific_context` fields `novelty_operationalization`,
`computational_envelope`, `evidence_policy`, `verification_boundary`, plus existing
scientific protocol fields. Unknown containers remain omitted and are reported.
Author scores do not cross the blind-review boundary.

Novelty feedback v2 sends a compact evidence overview plus each available
original passage exactly once. Selectable source references carry paper-bound
handles, so identical local span IDs cannot be rebound across papers. Original
quotes are still resolved by the manager; source integrity is not entailment.
Legacy reference pairs remain readable for archived runs.

The `preflight` research tool uses the same deterministic checks as formal
grading and exposes omissions before submission, without model calls or formal
attempt consumption. It does not bypass the final exact-byte grader check or
weaken the two-advisory-lineage/current-version requirements. Invalid scientific
claims and incomplete evidence remain visible; no historical output is rewritten.
