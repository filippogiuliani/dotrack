"""doTrack – Flask server: JSON API under /api and the built frontend (Svelte) as static files."""
import datetime
import os
import secrets
from urllib.parse import urlparse

from flask import Flask, abort, g, jsonify, request, send_from_directory

import auth
from famkit import backup
import caldav
import db
import hub_hooks
import i18n
from famkit import hub, oidc
import reminders
from api_calendar import bp as calendar_bp
from api_family import bp as family_bp
from api_items import bp as items_bp, cleanup_orphan_files
from api_lists import bp as lists_bp
from api_notifications import bp as notifications_bp
import security

# Requests that change nothing the family shares
QUIET = ('/api/notifications', '/api/push', '/api/login', '/api/logout', '/api/account', '/api/caldav', '/api/oidc')

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def _secret_key():
    if os.environ.get('DOTRACK_SECRET_KEY'):
        return os.environ['DOTRACK_SECRET_KEY']
    path = os.path.join(db.DATA_DIR, '.secret_key')
    if not os.path.exists(path):
        os.makedirs(db.DATA_DIR, exist_ok=True)
        with open(path, 'w') as f:
            f.write(secrets.token_hex(32))
        os.chmod(path, 0o600)
    with open(path) as f:
        return f.read().strip()


def create_app():
    db.init_db()
    app = Flask(__name__, static_folder=None)
    app.secret_key = _secret_key()
    app.config.update(
        SESSION_COOKIE_NAME='dotrack_session',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('DOTRACK_COOKIE_SECURE') == '1',
        PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=60),
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
        JSON_AS_ASCII=False,
    )
    if os.environ.get('DOTRACK_PROXY') == '1':
        # Behind a reverse proxy (nginx, Caddy, Traefik) that terminates HTTPS
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    hub.use(hub_hooks)
    oidc.use(auth, i18n.tr, lambda conn, name, email, invite, d:
             auth.create_user(conn, name, email, oidc.NO_PASSWORD, True, invite, d.get('language')))
    oidc.configure(app)
    for bp in (auth.bp, oidc.bp, hub.bp, family_bp, items_bp, calendar_bp, lists_bp, notifications_bp, caldav.bp, security.bp):
        app.register_blueprint(bp, url_prefix='/api')
    app.register_blueprint(caldav.dav)  # /dav/ and /.well-known/caldav, with its own sign-in (app passwords)

    @app.before_request
    def protect():
        # Requests that change data must come from this same origin (CSRF defense)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.path.startswith('/api/'):
            origin = request.headers.get('Origin') or request.headers.get('Referer')
            if origin and urlparse(origin).netloc != request.host:
                return jsonify(error=i18n.tr('Origin not allowed')), 403
        return auth.require_login()

    @app.after_request
    def bump_version(resp):
        # A change went through: clients polling /api/sync reload (the other person sees it within seconds)
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and resp.status_code < 400 and \
                request.path.startswith(('/api/', '/dav/')) and not request.path.startswith(QUIET) and getattr(g, 'family_id', None):
            try:
                with db.transaction() as conn:
                    db.bump(conn, g.family_id)
            except Exception as e:
                print(f'[sync] {e}', flush=True)
        return resp

    @app.get('/api/sync')
    def sync():
        """Cheap check polled every few seconds: the family's version and the unread notifications."""
        with db.transaction() as conn:
            v = conn.execute('SELECT version FROM families WHERE id = ?', (g.family_id,)).fetchone()
            unread = conn.execute('SELECT COUNT(*) FROM notifications WHERE user_id = ? AND family_id = ? AND read_at IS NULL',
                                  (g.user['id'], g.family_id)).fetchone()[0]
        return jsonify(version=v[0] if v else 0, unread=unread)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('Referrer-Policy', 'same-origin')
        resp.headers.setdefault('X-Frame-Options', 'DENY')
        resp.headers.setdefault('Content-Security-Policy', CSP)
        resp.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        if request.path.startswith('/api/'):
            resp.headers['Cache-Control'] = 'no-store'
        return resp

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(409)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def json_error(e):
        if request.path.startswith('/api/'):
            return jsonify(error=i18n.tr(getattr(e, 'description', str(e)))), e.code
        return e

    @app.get('/')
    @app.get('/<path:path>')
    def frontend(path='index.html'):
        if path.startswith('api/'):
            abort(404)
        if not os.path.isdir(STATIC_DIR):
            return 'Frontend not built: run "npm run build" in frontend/', 503
        if os.path.isfile(os.path.join(STATIC_DIR, path)):
            resp = send_from_directory(STATIC_DIR, path)
            if path.startswith('assets/'):
                resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            elif path == 'sw.js':
                resp.headers['Cache-Control'] = 'no-cache'  # a new service worker must be picked up at once
            return resp
        resp = send_from_directory(STATIC_DIR, 'index.html')
        resp.headers['Cache-Control'] = 'no-cache'
        return resp

    return app


if __name__ == '__main__':
    from waitress import serve
    app = create_app()
    backup.start_scheduler()
    reminders.start_scheduler()
    hub.start_sync()
    try:
        cleanup_orphan_files()
    except Exception as e:
        print(f'[files] cleanup failed: {e}', flush=True)
    port = int(os.environ.get('PORT', '3001'))
    if not auth.PASSWORD_LOGIN and not oidc.PROVIDERS:
        print('[doTrack] WARNING: password sign-in is off and no OIDC provider is configured: nobody can sign in', flush=True)
    print(f'[doTrack] listening on http://0.0.0.0:{port} – sign-up '
          f'{"open" if auth.SIGNUP_OPEN else "by invitation only"}', flush=True)
    # trusted_proxy: with DOTRACK_PROXY=1 the real client IP comes from the proxy (used by rate limiting)
    proxy = {'trusted_proxy': '*', 'trusted_proxy_headers': {'x-forwarded-for', 'x-forwarded-proto', 'x-forwarded-host'}} \
        if os.environ.get('DOTRACK_PROXY') == '1' else {}
    serve(app, host='0.0.0.0', port=port, threads=8, **proxy)
