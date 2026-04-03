# app.py

import time
import threading
import requests
import base64
from urllib.parse import urlparse
from flask import (Flask, render_template, abort, request, session,
                   redirect, url_for, jsonify, Response, g)
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
# Internet status cache — background thread, never blocks a request
# ---------------------------------------------------------------------------

_internet_status = {'online': False, 'checked_at': 0}
_internet_lock   = threading.Lock()

def _refresh_internet_status():
    while True:
        try:
            requests.get("http://detectportal.firefox.com/success.txt", timeout=3)
            online = True
        except Exception:
            online = False
        with _internet_lock:
            _internet_status['online']     = online
            _internet_status['checked_at'] = time.monotonic()
        time.sleep(15)

threading.Thread(target=_refresh_internet_status, daemon=True).start()

def get_internet_status():
    with _internet_lock:
        return _internet_status['online']

# ---------------------------------------------------------------------------
# Library section cache — per user, TTL 60s
# Avoids calling switchUser() + library.sections() on every page render.
# Stored in a module-level dict keyed by username; entries expire after 60s.
# ---------------------------------------------------------------------------

_section_cache      = {}   # {username: {'sections': [...], 'expires': monotonic}}
_section_cache_lock = threading.Lock()
_SECTION_TTL        = 60   # seconds

def get_cached_sections(user_plex, username):
    """Return library sections for this user, using a 60s in-memory cache."""
    now = time.monotonic()
    with _section_cache_lock:
        entry = _section_cache.get(username)
        if entry and entry['expires'] > now:
            return entry['sections']
    # Cache miss or expired — fetch fresh
    try:
        sections = user_plex.library.sections()
    except Exception:
        sections = []
    with _section_cache_lock:
        _section_cache[username] = {'sections': sections, 'expires': now + _SECTION_TTL}
    return sections

# ---------------------------------------------------------------------------
# Avatar proxy domain allowlist
# Only domains known to serve Plex user avatars are permitted.
# ---------------------------------------------------------------------------

_AVATAR_ALLOWED_HOSTS = {
    'plex.tv',
    'www.plex.tv',
    'metadata.provider.plex.tv',
    'users.plex.tv',
    'provider.plex.tv',
    'i.imgur.com',       # Plex allows Imgur avatars
    'gravatar.com',
    'www.gravatar.com',
    'secure.gravatar.com',
}

def is_allowed_avatar_url(url):
    """Return True if the URL host is on the avatar allowlist."""
    try:
        host = urlparse(url).hostname or ''
        # Allow exact match or any subdomain of an allowed host
        return any(
            host == allowed or host.endswith('.' + allowed)
            for allowed in _AVATAR_ALLOWED_HOSTS
        )
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Library type helpers
# ---------------------------------------------------------------------------

# Video library types get full sort options and watched/unwatched filtering.
# Music and photo sections use simpler options.
_VIDEO_SECTION_TYPES = {'movie', 'show'}
_MUSIC_SECTION_TYPES = {'artist'}
_PHOTO_SECTION_TYPES = {'photo'}

def section_sort_options(section_type):
    """Return list of (value, label) sort tuples appropriate for this section type."""
    base = [
        ('titleSort:asc',  'A – Z'),
        ('titleSort:desc', 'Z – A'),
        ('addedAt:desc',   'Recently Added'),
        ('addedAt:asc',    'Oldest Added'),
    ]
    if section_type in _VIDEO_SECTION_TYPES:
        base += [
            ('originallyAvailableAt:desc', 'Newest Release'),
            ('rating:desc',                'Top Rated'),
        ]
    if section_type in _MUSIC_SECTION_TYPES:
        base += [
            ('year:desc', 'Newest Release'),
        ]
    return base

def section_default_sort(section_type):
    return 'titleSort:asc'

def section_supports_unwatched(section_type):
    """Only video sections have a meaningful unwatched filter."""
    return section_type in _VIDEO_SECTION_TYPES

# ---------------------------------------------------------------------------
# Template context processor
# ---------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    """Inject server_title, is_online, and libraries into every template.
    Skipped for API/proxy/static routes that never render HTML.
    Library sections are cached per user for 60s to avoid repeated switchUser() calls.
    """
    path = request.path
    is_page_route = not (
        path.startswith('/api/')    or
        path.startswith('/proxy/')  or
        path.startswith('/static/') or
        path in ('/login', '/logout')
    )

    libs = []
    if is_page_route and plex and session.get('username'):
        try:
            user_plex = get_plex_instance()
            if user_plex:
                libs = get_cached_sections(user_plex, session['username'])
        except Exception:
            pass

    return {
        'server_title': server_title,
        'is_online':    get_internet_status(),
        'libraries':    libs,
    }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
            # Fix 3: API routes get a JSON 401, not a redirect, so the player
            # JS can detect session expiry and surface a proper message.
            if request.path.startswith('/api/'):
                return jsonify({'error': 'session_expired', 'ok': False}), 401
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
        if not hasattr(item, 'viewOffset') or item.viewOffset is None:
            item.viewOffset = 0
        if not hasattr(item, 'duration') or item.duration is None:
            item.duration = 0
    return items

def proxy_image(url):
    try:
        r = requests.get(url, timeout=5)
        return Response(r.content, content_type=r.headers.get('Content-Type', 'image/jpeg'))
    except Exception:
        transparent_png = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
        )
        return Response(transparent_png, content_type='image/png')

def get_streams(item):
    try:
        part  = item.media[0].parts[0]
        audio = []
        subs  = []
        for s in part.streams:
            label = s.extendedDisplayTitle or s.displayTitle or s.language or s.codec or f"Track {s.index}"
            if s.streamType == 2:
                audio.append({
                    'id':       s.id,
                    'index':    s.index,
                    'label':    label,
                    'selected': bool(s.selected),
                    'codec':    s.codec or '',
                    'channels': getattr(s, 'channels', None),
                })
            elif s.streamType == 3:
                subs.append({
                    'id':       s.id,
                    'index':    s.index,
                    'label':    label,
                    'selected': bool(s.selected),
                    'forced':   bool(getattr(s, 'forced', False)),
                    'codec':    s.codec or '',
                })
        return {'audio_streams': audio, 'subtitle_streams': subs, 'part_id': part.id}
    except Exception:
        return {'audio_streams': [], 'subtitle_streams': [], 'part_id': None}

def safe_total_size(section):
    try:
        return section.totalSize
    except AttributeError:
        return None

def get_extras(item):
    try:
        extras = item.extras()
        result = []
        for e in extras:
            result.append({
                'ratingKey': e.ratingKey,
                'title':     e.title,
                'subtype':   (e.subtype or 'extra')
                                .replace('behindTheScenes', 'Behind the Scenes')
                                .replace('sceneOrSample',   'Scene')
                                .replace('interview',       'Interview')
                                .replace('trailer',         'Trailer')
                                .replace('featurette',      'Featurette')
                                .replace('short',           'Short'),
                'duration':  e.duration or 0,
                'thumbUrl':  add_auth_to_url(e.thumb),
            })
        return result
    except Exception:
        return []

# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, title="Page Not Found",
                           message=str(e)), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, title="Server Error",
                           message=str(e)), 500

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def user_select():
    if not plex:
        return render_template('error.html', code=503,
                               title="Cannot Connect to Plex",
                               message=(
                                   "The launcher could not connect to your Plex server. "
                                   f"Check that PLEX_URL ({config.PLEX_URL}) and PLEX_TOKEN "
                                   "are correct in config.py, and that the server is running."
                               )), 503
    try:
        account = plex.myPlexAccount()
        users   = [account] + list(account.users())
        for user in users:
            user._thumbUrl = user.thumb
    except Exception:
        users = []
    return render_template('user_select.html', users=users)

@app.route('/proxy/avatar')
def proxy_avatar():
    url = request.args.get('url', '')
    if not url:
        abort(400)
    # Fix 4: domain allowlist — only proxy known Plex avatar hosts
    if not is_allowed_avatar_url(url):
        abort(403)
    return proxy_image(url)

@app.route('/api/status')
def api_status():
    return jsonify({'online': get_internet_status()})

@app.route('/login/<username>')
def login(username):
    session['username'] = username
    # Invalidate section cache on login so the new user's libraries load fresh
    with _section_cache_lock:
        _section_cache.pop(username, None)
    return redirect(url_for('home'))

@app.route('/logout')
def logout():
    username = session.get('username')
    session.clear()
    # Clear cached sections for this user on logout
    if username:
        with _section_cache_lock:
            _section_cache.pop(username, None)
    return redirect(url_for('user_select'))

@app.route('/home')
@login_required
def home(user_plex):
    on_deck        = enrich(user_plex.library.onDeck())
    recently_added = enrich(user_plex.library.recentlyAdded())
    return render_template('home_dashboard.html',
                           on_deck=on_deck,
                           recently_added=recently_added)

# ---------------------------------------------------------------------------
# Library — paginated, type-aware
# ---------------------------------------------------------------------------
PAGE_SIZE = 48

@app.route('/library/<library_key>')
@login_required
def library(user_plex, library_key):
    try:
        section      = user_plex.library.sectionByID(int(library_key))
        section_type = section.type   # 'movie', 'show', 'artist', 'photo'
        sort         = request.args.get('sort', section_default_sort(section_type))
        unwatched    = (request.args.get('unwatched', '0') == '1'
                        and section_supports_unwatched(section_type))
        total        = safe_total_size(section)
        sort_options = section_sort_options(section_type)

        # Validate sort value against allowed options to prevent injection
        allowed_sorts = {v for v, _ in sort_options}
        if sort not in allowed_sorts:
            sort = section_default_sort(section_type)

        kwargs = dict(sort=sort, container_start=0, container_size=PAGE_SIZE, maxresults=PAGE_SIZE)
        if unwatched:
            kwargs['unwatched'] = True

        items = enrich(section.search(**kwargs))

        return render_template('library.html',
                               section=section,
                               section_type=section_type,
                               items=items,
                               total=total if total is not None else 999999,
                               display_total=total if total is not None else '?',
                               page_size=PAGE_SIZE,
                               sort=sort,
                               sort_options=sort_options,
                               supports_unwatched=section_supports_unwatched(section_type),
                               unwatched=unwatched)
    except Exception as e:
        abort(404, f"Library not found: {e}")

@app.route('/api/library/<library_key>/page')
@login_required
def library_page(user_plex, library_key):
    try:
        section      = user_plex.library.sectionByID(int(library_key))
        section_type = section.type
        offset       = int(request.args.get('offset', 0))
        sort         = request.args.get('sort', section_default_sort(section_type))
        unwatched    = (request.args.get('unwatched', '0') == '1'
                        and section_supports_unwatched(section_type))

        allowed_sorts = {v for v, _ in section_sort_options(section_type)}
        if sort not in allowed_sorts:
            sort = section_default_sort(section_type)

        kwargs = dict(sort=sort, container_start=offset, container_size=PAGE_SIZE, maxresults=PAGE_SIZE)
        if unwatched:
            kwargs['unwatched'] = True

        items = enrich(section.search(**kwargs))
        cards = []
        for item in items:
            vo  = item.viewOffset or 0
            dur = item.duration   or 0
            cards.append({
                'ratingKey':     item.ratingKey,
                'title':         item.title,
                'year':          item.year,
                'thumbUrl':      item.thumbUrl,
                'isWatched':     getattr(item, 'isWatched', False),
                'pct':           int(vo / dur * 100) if dur > 0 else 0,
                'section_type':  section_type,
            })
        return jsonify({'cards': cards, 'offset': offset, 'count': len(cards)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/item/<int:rating_key>')
@login_required
def item_details(user_plex, rating_key):
    try:
        item = user_plex.fetchItem(rating_key)
        item.thumbUrl = add_auth_to_url(item.thumb)
        item.artUrl   = add_auth_to_url(item.art)

        next_unwatched = None
        extras         = []

        if item.type == 'show':
            seasons_data = item.seasons()
            for season in seasons_data:
                season.thumbUrl = add_auth_to_url(season.thumb)
                for episode in season.episodes():
                    episode.thumbUrl = add_auth_to_url(episode.thumb)
            item._cached_seasons = seasons_data
            try:
                next_unwatched = item.onDeck()
            except Exception:
                pass
            extras = get_extras(item)

        elif item.type == 'movie':
            extras = get_extras(item)

        return render_template('item_details.html',
                               item=item,
                               next_unwatched=next_unwatched,
                               extras=extras)
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
    return redirect(url_for('player', rating_key=rating_key) + '?force_start=1')

@app.route('/player/<int:rating_key>')
@login_required
def player(user_plex, rating_key):
    try:
        item = user_plex.fetchItem(rating_key)
        item.thumbUrl = add_auth_to_url(item.thumb)
        item.artUrl   = add_auth_to_url(item.art)

        force_start = request.args.get('force_start') == '1'
        view_offset = 0 if force_start else (item.viewOffset or 0)
        duration_ms = item.duration or 0
        resumable   = view_offset > 30_000 and duration_ms > 0 and view_offset < duration_ms - 60_000

        streams           = get_streams(item)
        selected_audio    = next((s for s in streams['audio_streams']    if s['selected']), None)
        selected_subtitle = next((s for s in streams['subtitle_streams'] if s['selected']), None)

        stream_url = _build_stream_url(
            item.ratingKey, view_offset,
            audio_stream_id    = selected_audio['id']    if selected_audio    else None,
            subtitle_stream_id = selected_subtitle['id'] if selected_subtitle else None,
        )

        show_rating_key = None
        prev_ep = next_ep = None
        if item.type == 'episode':
            show_rating_key = getattr(item, 'grandparentRatingKey', None)
            if show_rating_key is None:
                try:
                    show_rating_key = item.show().ratingKey
                except Exception:
                    pass
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
                               next_ep=next_ep,
                               streams=streams,
                               show_rating_key=show_rating_key,
                               config_url=config.PLEX_URL)
    except NotFound:
        abort(404, "Media not found.")

def _build_stream_url(rating_key, offset_ms, audio_stream_id=None, subtitle_stream_id=None):
    params = (
        f"hasMDE=1&path=/library/metadata/{rating_key}"
        f"&mediaIndex=0&partIndex=0&protocol=hls&fastSeek=1"
        f"&directPlay=1&directStream=1&subtitleSize=100&audioBoost=100"
        f"&X-Plex-Token={config.PLEX_TOKEN}"
        f"&X-Plex-Client-Identifier=plex-offline-launcher"
        f"&X-Plex-Product=PlexOfflineLauncher&X-Plex-Version=1.0"
        f"&X-Plex-Platform=Chrome&offset={offset_ms // 1000}"
    )
    if audio_stream_id    is not None: params += f"&audioStreamID={audio_stream_id}"
    if subtitle_stream_id is not None: params += f"&subtitleStreamID={subtitle_stream_id}"
    return f"{config.PLEX_URL}/video/:/transcode/universal/start.m3u8?{params}"

@app.route('/api/stream_url/<int:rating_key>')
@login_required
def api_stream_url(user_plex, rating_key):
    offset_ms          = int(request.args.get('offset_ms', 0))
    audio_stream_id    = request.args.get('audio_id',    None)
    subtitle_stream_id = request.args.get('subtitle_id', None)
    if audio_stream_id    is not None: audio_stream_id    = int(audio_stream_id)
    if subtitle_stream_id is not None: subtitle_stream_id = int(subtitle_stream_id)
    if subtitle_stream_id == 0:        subtitle_stream_id = None
    url = _build_stream_url(rating_key, offset_ms,
                            audio_stream_id=audio_stream_id,
                            subtitle_stream_id=subtitle_stream_id)
    return jsonify({'stream_url': url})

@app.route('/api/scrobble/<int:rating_key>', methods=['POST'])
@login_required
def scrobble(user_plex, rating_key):
    data      = request.get_json(silent=True) or {}
    offset_ms = data.get('offset_ms', 0)
    state     = data.get('state', 'playing')
    try:
        params = {
            'ratingKey': rating_key,
            'key':       f'/library/metadata/{rating_key}',
            'state':     state,
            'time':      int(offset_ms),
            'duration':  data.get('duration_ms', 0),
            'X-Plex-Token':              config.PLEX_TOKEN,
            'X-Plex-Client-Identifier': 'plex-offline-launcher',
            'X-Plex-Product':           'PlexOfflineLauncher',
            'X-Plex-Version':           '1.0',
        }
        try:
            params['X-Plex-Token'] = user_plex._token
        except Exception:
            pass
        requests.get(f"{config.PLEX_URL}/:/timeline", params=params, timeout=5)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/search')
@login_required
def search(user_plex):
    query   = request.args.get('query', '').strip()
    results = enrich(user_plex.search(query)) if query else []
    return render_template('search_results.html', query=query, results=results)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
