# Account-protected team console

`python -m sage.team_console` serves the existing console and the real
`sage.console.RunStore`, including original artifacts and the same bounded
autonomous launcher. This is a small single-process, trusted-group deployment,
with no database. All signed-in members can view/download every run and start
research using the server's model account. Only administrators can add members
and configure the provider. There is no per-project isolation or monetary quota.

## Set up once

Use Python 3.10+ in the same environment as the research runner. Keep private
state **outside the public repository**; initialization refuses to replace
existing accounts and reads the initial password with a hidden prompt:

```bash
python -m sage.team_console --state /private/sage-team --init-admin admin
```

In a separate process, start the loopback service:

```bash
python -m sage.team_console --state /private/sage-team --port 8780
```

By default the repository is resolved from the module location. `--repo` can
point to the checkout whose `projects/` and console assets should be served.
An optional `--bundle /private/exports/research.zip` enables a complete archive
download in settings. Without it, that link is hidden; individual artifact
downloads still work. An archive is served byte-for-byte, not generated or
redacted on demand, so review its contents before configuring it.

## HTTPS entry point

Place a TLS reverse proxy or a Cloudflare Tunnel in front of `127.0.0.1:8780`.
Do not publish the loopback port directly. For a temporary free development
entry, the official `cloudflared` client supports:

```bash
cloudflared tunnel --url http://127.0.0.1:8780 --protocol http2
```

Write the exact issued HTTPS origin, without a trailing slash, to the private
state directory's `public-origin.txt`. For example, if the issued URL is
`https://example.trycloudflare.com`, that file must contain precisely that origin.
The gateway rejects requests until a matching Host is configured. Every POST
also requires that exact Origin. The `__Host-` Secure cookie requires HTTPS.
The connector must preserve the public Host and point only to this loopback
service. For other proxies, strip untrusted forwarded headers and configure
rate limiting appropriately; the gateway uses Cloudflare's connecting-IP header
for login throttling when present.

[Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)
are temporary development endpoints, have no uptime guarantee, and receive a
new random hostname when the connector restarts. Keep the connector running
during gateway-only updates to retain the current URL. The compute server and
its model/API usage are separate from the tunnel's price. For sustained use,
configure a stable authenticated tunnel/reverse proxy and suitable operational
controls; this repository does not create a cloud account or domain.

## Accounts, keys and operation

Sign in, change your initial password, then add members in **账号与模型设置**.
Passwords are salted scrypt hashes; sessions expire after 12 hours and are
revoked when that user changes their password. Logout removes the current
session and browser tab storage. A gateway restart invalidates all sessions.
There is no public registration or automatic credential recovery.

The admin page currently configures DeepSeek Flash. Saving a key stores it in
private `provider.json` and installs it in the server environment; it performs
no paid test. Child researchers inherit it at launch. The key is never returned
to the browser, and changes are refused during an active research run. Missing
credentials leave the platform usable for viewing, exporting and planning, with
research starts disabled. API spending still needs to be monitored at the provider.

The service uses an HttpOnly, Secure, SameSite session cookie, per-session CSRF
tokens, exact-origin checking, bounded login throttling, authenticated data
routes, and a content security policy. Passwords/keys/topics are omitted from
access audit records; starts include the initiating username and run ID.
These controls assume a trusted host and loopback proxy, not an OS sandbox for
generated research. Back up private state and artifacts separately with suitable
filesystem permissions; Linux credential files use mode 0600 and state 0700.

Before deployment updates, inspect real launcher identities and wait for active
research to end. Do not replace scientific source, restart the gateway that owns
a live child, or start a new run as a health check. The gateway's process reaper
owns exit-code recording. Preserve run directories and original exports. Restart
only the idle gateway after verification, keeping the connector and private
state intact. Stop commands and service supervision are deployment-specific;
the module does not automatically power on a server or resume research.

Never commit `users.json`, `provider.json`, private state, credentials, exported
research archives or the cloudflared binary. Public code consists of
`sage/team_console.py`, `sage/team_console_static/`, tests, and these instructions.

## Offline verification

```bash
python scripts/check.py
node tests/planner.test.js
node tests/console_client.test.js
```

The gateway tests exercise HTTP authentication, CSRF, member/admin boundaries,
static planning routes, key-change guards and exact artifact delegation using a
mock RunStore. Console lifecycle tests separately cover the real launch contract
with fake subprocesses. Passing these checks does not demonstrate live provider
access, research quality, model balance or a completed scientific experiment.
