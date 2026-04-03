# Plex Offline Launcher

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

## Features

- 👨‍👩‍👧‍👦 **Family User Switching** — "Who's Watching?" screen with proxied avatars (works offline)
- ✅ **Separate Watch Histories** — On Deck and watched/unwatched status unique to each user
- ▶ **Resume Playback** — picks up where you left off, per user
- 📡 **Progress Scrobbling** — reports playback position back to Plex every 10 seconds, so On Deck stays accurate across all your devices
- 🚫 **Zero CDN Dependencies** — hls.js is bundled locally; no Google Fonts, no external scripts. Works 100% offline after install
- 🎮 **Full Player Controls** — custom seek bar, volume, mute, fullscreen, +/−10s skip, keyboard shortcuts
- ⌨️ **Keyboard Shortcuts** — Space/K (play/pause), ←/→ (±10s), ↑/↓ (volume), F (fullscreen), M (mute)
- 📊 **Progress Bars on Cards** — in-progress items show how far through you are
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
│   │   ├── home_dashboard.html
│   │   ├── item_details.html
│   │   ├── library.html
│   │   ├── player.html
│   │   ├── search_results.html
│   │   └── user_select.html
│   ├── app.py
│   ├── config.py
│   └── requirements.txt
└── README.md
```

---

## Installation & Setup

### 1. Install Dependencies

```bash
cd src
pip install -r requirements.txt
```

### 2. Configure `config.py`

```python
# config.py

PLEX_URL   = 'http://192.168.1.100:32400'   # Your server's local IP and port
PLEX_TOKEN = 'YourPlexTokenHere'            # Admin token (see below)
SECRET_KEY = 'any-long-random-string-here'  # For session security
```

**Finding your Plex token:**
1. Open Plex Web, go to any media item
2. Click `···` → Get Info → View XML
3. Copy the `X-Plex-Token=` value from the URL

### 3. Run

```bash
flask --app app run --host=0.0.0.0
```

Or directly:

```bash
python app.py
```

### 4. Access

Open a browser on any device on your network:

```
http://<your_server_ip>:5000
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

## Troubleshooting

**Can't connect from another device?**
Add an inbound firewall rule for TCP port 5000 on the server machine.

**Stream won't play?**
The player uses Plex's HLS transcode endpoint, which requires Plex to be running.
Direct play is requested first; Plex transcodes automatically if the format isn't compatible.

**No users shown on the selector screen?**
Check that `PLEX_TOKEN` in config.py is the admin token. Managed user accounts
are fetched via the admin account's `myPlexAccount()`.

**Avatars not loading?**
User avatars are fetched from plex.tv and proxied through the local server
(`/proxy/avatar`). They appear when online and are cached by the browser for
subsequent offline visits.

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

## License

MIT License
