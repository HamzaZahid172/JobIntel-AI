# Fix a stale local dashboard and diagnose Gmail (Mac)

**This preserves Docker volumes and existing JobIntel profiles, uploaded CVs,
PostgreSQL applications and local Ollama models.**

## Step 1. Work in the directory actually used by Docker

Open Terminal. Change to your own JobIntel-AI clone, then run:

```bash
pwd
git status --short
git remote -v
git fetch origin
git switch main
git pull --ff-only origin main
git rev-parse --short HEAD
```

If `git switch` or `git pull` reports local modifications, keep them and
review them before proceeding. Do not blindly reset your worktree.

## Step 2. Find who owns the web port

```bash
docker compose ps
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
lsof -nP -iTCP:3100 -sTCP:LISTEN
```

If port 3100 belongs to a container from a **different Compose project**,
stop that exact old container/project after identifying it. Running a rebuild
in a second directory will not replace the container on port 3100.

## Step 3. Rebuild only application images and recreate containers

```bash
docker compose down --remove-orphans
docker compose build --no-cache frontend backend
docker compose up -d --force-recreate --remove-orphans
docker compose ps
```

`docker compose down` WITHOUT `-v` leaves named volumes intact.
Never run `docker compose down -v`, `docker volume prune`, or
`docker system prune --volumes` to fix a stale UI.

## Step 4. Prove which build is running

```bash
curl -fsS http://localhost:3100/version.json
curl -sSI http://localhost:3100/app.js | grep -Ei 'HTTP/|Cache-Control|X-JobIntel-Build'
curl -fsS http://localhost:8100/health
```

The frontend version must be **2026.10.26.1** and the app page must show
`Build 2026.10.26.1 · Sync All` in the sidebar. If not, inspect
`docker ps` for a second container or another clone. You can open an
incognito tab after the correct container responds, or use Cmd+Shift+R.

## Step 5. Diagnose Gmail without pasting access tokens

Navigate to **Settings → Gmail permissions & application tracking →
Test Gmail connection**. The diagnostic checks Google authorization and the
Gmail profile endpoint, not mail content. It reports one of:

- CONNECTED: mailbox access works. Return to My Applications. Sync is automatic
  on page entry and periodically while the tab is active.
- NOT_CONNECTED / TOKEN_MISSING / TOKEN_REJECTED: reconnect Gmail with the
  **read-only** scope.
- MISSING_READ_SCOPE / GMAIL_FORBIDDEN: verify Gmail API is enabled in the
  selected Google Cloud project and the OAuth client/permissions are correct.
- NETWORK_UNAVAILABLE / NETWORK_TIMEOUT: check Docker DNS, HTTPS, firewall,
  VPN, proxy and local internet connectivity.
- GOOGLE_RATE_LIMIT: avoid repeated forced sync and retry later.

Google Sign-In is separate from granting Gmail read-only access.

Optional network check that sends **no OAuth credentials**:

```bash
docker compose exec backend python -c "import urllib.request,urllib.error; u='https://gmail.googleapis.com/gmail/v1/users/me/profile'; exec('try:\\n r=urllib.request.urlopen(u,timeout=8); print(r.status)\\nexcept urllib.error.HTTPError as e:\\n print(e.code, 'Google reached (authentication expected)')\\nexcept Exception as e:\\n print(type(e).__name__, 'network check failed')')"
```

A 401 response to this unauthenticated test indicates that network routing
reaches Google; it is **not** an OAuth pass.

If still broken:

```bash
docker compose logs --tail=80 backend
docker compose logs --tail=40 frontend
```

Before sharing logs, remove bearer tokens, secret values, email contents and
other private data. A screenshot proving that an employer rejected you can be
recorded manually as a Rejected application, independently of Gmail sync.

## App behavior

My Applications has exactly **one** Sync All Applications button.
The page refreshes saved statuses after a successful targeted batch scan.
The dashboard fetches data without blocking on Gmail. Auto-sync is throttled;
it cannot run without a valid Gmail connection or internet access.

Successful local rebuild and Google permission checks are required after CI:
CI validates code but does not deploy to your Mac.
