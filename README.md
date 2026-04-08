# Plex Offline Launcher v3.0

A family-friendly, self-hosted web client for your Plex Media Server — designed
for full functionality during internet outages. Multi-user, no CDN dependencies,
with resume support and automatic progress scrobbling.

**Last Updated:** April 2026

---

## The Problem

Plex is fantastic, but its reliance on plex.tv for authentication can be a major
issue. If your internet connection goes down, many Plex client apps are unable to
sign in — locking you out of your media library even though the server is sitting
right there on your local network.

## The Solution

A self-hosted web interface that runs directly on your Plex server. It uses Python
and Flask to connect to your Plex server's local API with a pre-authorised token,
bypassing the need for an internet connection entirely.

---

## What's New in v3.0

- **Environment-based config** — credentials live in `.env`, never in source code
- **Startup validation** — clear errors on missing or placeholder config values
- **User token cache** — avoids a Plex API round-trip on every request
- **Connectivity cache** — internet check is cached; no latency penalty per page
- **CSRF protection** — all state-changing routes verify a per-session token
- **Scoped avatar proxy** — only proxies from known plex.tv CDN hosts
- **Username validation on login** — rejects logins for users not in your Plex account
- **Structured logging** — rotating log file at `src/logs/app.log` + console output
- **Production WSGI server** — Waitress replaces Flask's dev server
- **`/health` endpoint** — for uptime monitors and reverse-proxy checks
- **Rate-limited scrobble API** — 60 calls/min per IP
- **Proper error pages** — 403, 404, 500, 503 all render a styled error template
- **Full exception handling** — no silent swallowing of errors

---

## Features

- 👨‍👩‍👧‍👦 **Family User Switching** — "Who's Watching?" screen with proxied avatars (works offline)
- ✅ **Separate Watch Histories** — On Deck and watched/unwatched status unique to each user
- ▶ **Resume Playback** — picks up where you left off, per user
- 📡 **Progress Scrobbling** — reports playback position back to Plex every 10 seconds
- 🚫 **Zero CDN Dependencies** — hls.js is bundled locally; no Google Fonts, no external scripts
- 🎮 **Full Player Controls** — seek bar, volume, mute, fullscreen, ±10s skip, keyboard shortcuts
- ⌨️ **Keyboard Shortcuts** — Space/K (play/pause), ←/→ (±10s), ↑/↓ (volume), F (fullscreen), M (mute)
- 📊 **Progress Bars** — in-progress items show how far through you are
- 📺 **Full TV Show Browsing** — navigate from show → season → episode list
- 🔍 **Integrated Search** — search bar in every page header
- 🌐 **Network Accessible** — works from any phone, tablet, or computer on your local network

---

## Project Structure

```
plex-offline-launcher/
├── src/
│   ├── static/
│   │   └── js/
│   │       └── hls.min.js          ← bundled locally (no CDN)
│   ├── templates/
│   │   ├── base.html
│   │   ├── error.html              ← NEW: styled error pages
│   │   ├── home_dashboard.html
│   │   ├── item_details.html
│   │   ├── library.html
│   │   ├── player.html
│   │   ├── search_results.html
│   │   └── user_select.html
│   ├── logs/                       ← NEW: rotating log files (git-ignored)
│   ├── app.py                      ← main Flask application
│   ├── config.py                   ← NEW: validated env-based config
│   ├── logger.py                   ← NEW: structured logging setup
│   ├── plex_client.py              ← NEW: connection, cache, helpers
│   └── requirements.txt
├── run.py                          ← NEW: production WSGI entry point
├── pyproject.toml
├── .env.example                    ← NEW: config template
├── .env                            ← YOUR config (never commit this)
├── .gitignore
└── README.md
```

---

## Installation & Setup

### 1. Install Dependencies

```bash
pip install -r src/requirements.txt
```

### 2. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
PLEX_URL=http://192.168.1.100:32400
PLEX_TOKEN=YourPlexTokenHere
SECRET_KEY=a-long-random-string-you-generate
```

**Generating a secure SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Finding your Plex token:**
1. Open Plex Web, go to any media item
2. Click `···` → Get Info → View XML
3. Copy the `X-Plex-Token=` value from the URL

### 3. Run (Production)

```bash
python run.py
```

This starts Waitress — a production-grade WSGI server — on port 5000.

### 4. Run (Development)

```bash
cd src
flask --app app run --host=0.0.0.0 --debug
```

### 5. Access

Open a browser on any device on your network:

```
http://<your_server_ip>:5000
```

---

## Optional Configuration

All of these go in your `.env` file:

| Variable | Default | Description |
|---|---|---|
| `PLEX_CONNECT_TIMEOUT` | `10` | Seconds to wait when connecting to Plex on startup |
| `USER_CACHE_TTL` | `300` | Seconds to cache per-user Plex tokens (5 minutes) |
| `CONNECTIVITY_CACHE_TTL` | `30` | Seconds to cache the internet connectivity check |
| `PORT` | `5000` | Port to listen on |
| `LOG_LEVEL` | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Running Behind a Reverse Proxy (Nginx / Caddy)

For HTTPS access on your LAN, put Nginx or Caddy in front and set
`SESSION_COOKIE_SECURE = True` in `src/app.py`.

**Minimal Nginx config:**

```nginx
server {
    listen 443 ssl;
    server_name plex.yourdomain.local;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_buffering    off;
    }
}
```

---

## Health Check

`GET /health` returns JSON — useful for uptime monitors:

```json
{
  "status": "ok",
  "plex_connected": true,
  "plex_server": "My Plex Server"
}
```

---

## Logs

Logs are written to `src/logs/app.log` (rotating, 5 MB × 3 files) and to stdout.
The logs directory is git-ignored.

```bash
tail -f src/logs/app.log
```

---

## How Resume & Scrobbling Work

The player reports your playback position to Plex every 10 seconds via
`/api/scrobble/<rating_key>`, and again when you pause or navigate away.
This updates Plex's internal timeline so:

- **On Deck** stays current across all your Plex clients
- **"Continue Watching"** cards show accurate progress bars
- **Resuming** in this launcher picks up from your last position

---

## Security Notes

- Credentials are loaded from `.env` — never hardcoded
- The `.env` file is git-ignored and must never be committed
- All state-changing routes (mark watched/unwatched, scrobble) require a CSRF token
- The avatar proxy validates the host against a known-safe allowlist
- User login is validated against the actual Plex account user list
- Sessions have a 14-day lifetime with `HttpOnly` and `SameSite=Lax` cookies

> **Note on stream URLs:** The Plex token appears in the HLS stream URL that
> the player JS constructs. This is a known Plex API constraint — HLS streams
> require token-based auth in the query string. The URL is only accessible on
> your local network. For higher security, this could be wrapped in a signed
> short-lived server-side proxy route.

---

## Keyboard Shortcuts (Player)

| Key | Action |
|-----|--------|
| Space / K | Play / Pause |
| ← / → | Seek ±10 seconds |
| ↑ / ↓ | Volume ±10% |
| F | Toggle fullscreen |
| M | Toggle mute |

---

## Troubleshooting

**Can't connect from another device?**
Add an inbound firewall rule for TCP port 5000 on the server machine.

**Stream won't play?**
The player uses Plex's HLS transcode endpoint, which requires Plex to be running.
Direct play is requested first; Plex transcodes automatically if the format isn't compatible.

**No users shown on the selector screen?**
Check that `PLEX_TOKEN` in `.env` is the admin token.

**Avatars not loading?**
User avatars are proxied through the local server (`/proxy/avatar`). They load
when online and are cached by the browser for subsequent offline visits.

**Startup config error?**
The app validates your `.env` at startup and prints a clear message if anything
is missing or still set to a placeholder value.

---

## License

MIT License
