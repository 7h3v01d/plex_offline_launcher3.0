# app.py

import requests
import base64
from flask import Flask, render_template, abort, request, session, redirect, url_for, jsonify, Response
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound
from functools import wraps
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

try:
    print("Connecting to Plex server as admin...")
    plex = PlexServer(config.PLEX_URL, config.PLEX_TOKEN, timeout=10)
    server_title = plex.friendlyName
    print(f"✅ Connection to '{server_title}' successful!")
except Exception as e:
    plex = None
    server_title = "Plex Server (Connection Failed)"
    print(f"❌ Could not connect to Plex. Error: {e}")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_internet_connection():
    try:
        requests.get("http://detectportal.firefox.com/success.txt", timeout=3)
        return True
    except (requests.ConnectionError, requests.Timeout):
        return False

def add_auth_to_url(url):
    if not url:
        return None
    return f"{config.PLEX_URL}{url}?X-Plex-Token={config.PLEX_TOKEN}"

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not plex:
            abort(500, "Plex server not connected.")
        user_plex = get_plex_instance()
        if not user_plex:
            return redirect(url_for('user_select'))
        return f(*args, **kwargs, user_plex=user_plex)
    return decorated

def get_plex_instance():
    username = session.get('username')
    if not username:
        return None
    try:
        return plex.switchUser(username)
    except Exception:
        return plex

def enrich(items):
    for item in items:
        item.thumbUrl = add_auth_to_url(item.thumb)
        # Ensure these attributes exist for template progress bars
        if not hasattr(item, 'viewOffset') or item.viewOffset is None:
            item.viewOffset = 0
        if not hasattr(item, 'duration') or item.duration is None:
            item.duration = 0
    return items

def proxy_image(url):
    """Fetch an external image and return it as a proxied response.
    Used for user avatars which come from plex.tv (unavailable offline).
    """
    try:
        r = requests.get(url, timeout=5)
        return Response(r.content, content_type=r.headers.get('Content-Type', 'image/jpeg'))
    except Exception:
        # Return a 1x1 transparent PNG as fallback
        transparent_png = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
        )
        return Response(transparent_png, content_type='image/png')

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def user_select():
    if not plex:
        abort(500, "Plex server not connected.")
    try:
        account = plex.myPlexAccount()
        users = [account] + list(account.users())
        for user in users:
            # Store the original external thumb URL; we'll proxy it
            user._thumbUrl = user.thumb
    except Exception:
        users = []
    is_online = check_internet_connection()
    return render_template('user_select.html',
                           users=users,
                           server_title=server_title,
                           is_online=is_online)

@app.route('/proxy/avatar')
def proxy_avatar():
    """Proxy user avatar images so they work offline after first load.
    The browser fetches /proxy/avatar?url=<external_url> from our local server.
    """
    url = request.args.get('url', '')
    if not url:
        abort(400)
    return proxy_image(url)

@app.route('/login/<username>')
def login(username):
    session['username'] = username
    return redirect(url_for('home'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('user_select'))

@app.route('/home')
@login_required
def home(user_plex):
    is_online = check_internet_connection()
    on_deck = enrich(user_plex.library.onDeck())
    recently_added = enrich(user_plex.library.recentlyAdded())
    libraries = user_plex.library.sections()
    return render_template('home_dashboard.html',
                           server_title=server_title,
                           is_online=is_online,
                           on_deck=on_deck,
                           recently_added=recently_added,
                           libraries=libraries)

@app.route('/library/<library_key>')
@login_required
def library(user_plex, library_key):
    is_online = check_internet_connection()
    try:
        section = user_plex.library.sectionByID(int(library_key))
        items = enrich(section.all())
        return render_template('library.html',
                               section=section,
                               items=items,
                               server_title=server_title,
                               is_online=is_online)
    except Exception:
        abort(404, "Library not found.")

@app.route('/item/<int:rating_key>')
@login_required
def item_details(user_plex, rating_key):
    is_online = check_internet_connection()
    try:
        item = user_plex.fetchItem(rating_key)
        item.thumbUrl = add_auth_to_url(item.thumb)
        item.artUrl = add_auth_to_url(item.art)
        if item.type == 'show':
            for season in item.seasons():
                season.thumbUrl = add_auth_to_url(season.thumb)
                for episode in season.episodes():
                    episode.thumbUrl = add_auth_to_url(episode.thumb)
        return render_template('item_details.html',
                               item=item,
                               server_title=server_title,
                               is_online=is_online)
    except NotFound:
        abort(404, "Media not found.")

@app.route('/item/<int:rating_key>/mark_watched')
@login_required
def mark_watched(user_plex, rating_key):
    item = user_plex.fetchItem(rating_key)
    item.markWatched()
    return redirect(url_for('item_details', rating_key=rating_key))

@app.route('/item/<int:rating_key>/mark_unwatched')
@login_required
def mark_unwatched(user_plex, rating_key):
    item = user_plex.fetchItem(rating_key)
    item.markUnwatched()
    return redirect(url_for('item_details', rating_key=rating_key))

@app.route('/player/<int:rating_key>/fresh')
@login_required
def player_fresh(user_plex, rating_key):
    """Play from the beginning regardless of stored viewOffset."""
    try:
        item = user_plex.fetchItem(rating_key)
        # Temporarily zero out the offset for this request
        item.viewOffset = 0
    except NotFound:
        abort(404, "Media not found.")
    # Redirect to normal player — but we need the offset=0 version.
    # Easiest: just call player() logic directly with offset forced to 0.
    return redirect(url_for('player', rating_key=rating_key) + '?force_start=1')

@app.route('/player/<int:rating_key>')
@login_required
def player(user_plex, rating_key):
    try:
        item = user_plex.fetchItem(rating_key)
        item.thumbUrl = add_auth_to_url(item.thumb)
        item.artUrl = add_auth_to_url(item.art)

        # Resume offset in milliseconds (0 = start from beginning)
        force_start = request.args.get('force_start') == '1'
        view_offset = 0 if force_start else (item.viewOffset or 0)
        duration_ms = item.duration or 0

        # Determine whether there's meaningful progress to resume from
        # (ignore if within first 30s or within last 60s — treat as "start over")
        resumable = (
            view_offset > 30_000 and
            duration_ms > 0 and
            view_offset < duration_ms - 60_000
        )

        # Build stream URL. Prefer direct play; Plex will transcode if needed.
        # We append the offset so playback resumes correctly.
        stream_url = (
            f"{config.PLEX_URL}/video/:/transcode/universal/start.m3u8"
            f"?hasMDE=1"
            f"&path=/library/metadata/{item.ratingKey}"
            f"&mediaIndex=0"
            f"&partIndex=0"
            f"&protocol=hls"
            f"&fastSeek=1"
            f"&directPlay=1"
            f"&directStream=1"
            f"&subtitleSize=100"
            f"&audioBoost=100"
            f"&X-Plex-Token={config.PLEX_TOKEN}"
            f"&X-Plex-Client-Identifier=plex-offline-launcher"
            f"&X-Plex-Product=PlexOfflineLauncher"
            f"&X-Plex-Version=1.0"
            f"&X-Plex-Platform=Chrome"
            f"&offset={view_offset // 1000}"  # Plex offset is in seconds for transcode URL
        )

        prev_ep = next_ep = None
        if item.type == 'episode':
            siblings = list(item.show().episodes())
            idx = next((i for i, e in enumerate(siblings) if e.ratingKey == item.ratingKey), None)
            if idx is not None:
                if idx > 0:
                    prev_ep = siblings[idx - 1]
                if idx < len(siblings) - 1:
                    next_ep = siblings[idx + 1]

        return render_template('player.html',
                               item=item,
                               stream_url=stream_url,
                               view_offset=view_offset,
                               duration_ms=duration_ms,
                               resumable=resumable,
                               prev_ep=prev_ep,
                               next_ep=next_ep)
    except NotFound:
        abort(404, "Media not found.")

@app.route('/api/scrobble/<int:rating_key>', methods=['POST'])
@login_required
def scrobble(user_plex, rating_key):
    """Called by the player JS to report playback progress back to Plex.
    Keeps On Deck accurate and enables resume across sessions/devices.
    """
    data = request.get_json(silent=True) or {}
    offset_ms = data.get('offset_ms', 0)   # current position in milliseconds
    state = data.get('state', 'playing')   # 'playing', 'paused', 'stopped'

    try:
        # Use the raw Plex API timeline endpoint to update progress
        params = {
            'ratingKey': rating_key,
            'key': f'/library/metadata/{rating_key}',
            'state': state,
            'time': int(offset_ms),
            'duration': data.get('duration_ms', 0),
            'X-Plex-Token': config.PLEX_TOKEN,
            'X-Plex-Client-Identifier': 'plex-offline-launcher',
            'X-Plex-Product': 'PlexOfflineLauncher',
            'X-Plex-Version': '1.0',
        }
        # Switch to user token if needed
        if session.get('username'):
            try:
                user_token = user_plex._token
                params['X-Plex-Token'] = user_token
            except Exception:
                pass

        requests.get(f"{config.PLEX_URL}/:/timeline", params=params, timeout=5)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/search')
@login_required
def search(user_plex):
    query = request.args.get('query', '').strip()
    is_online = check_internet_connection()
    results = []
    if query:
        results = enrich(user_plex.search(query))
    return render_template('search_results.html',
                           query=query,
                           results=results,
                           server_title=server_title,
                           is_online=is_online)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
