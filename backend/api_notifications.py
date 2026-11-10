"""API: in-app notifications (the bell) and Web Push subscriptions."""
from urllib.parse import urlparse

from flask import Blueprint, abort, g, jsonify

import db
import i18n
import notify
from common import body

bp = Blueprint('notifications', __name__)

MAX_SUBSCRIPTIONS = 20  # devices per user


@bp.get('/notifications')
def get_notifications():
    """Latest notifications of the current family, newest first, with the number still unread."""
    with db.transaction() as conn:
        rows = [dict(r) for r in conn.execute(
            '''SELECT id, item_id, actor_id, kind, title, body, read_at, created_at FROM notifications
               WHERE user_id = ? AND family_id = ? ORDER BY id DESC LIMIT 50''', (g.user['id'], g.family_id))]
        unread = conn.execute('SELECT COUNT(*) FROM notifications WHERE user_id = ? AND family_id = ? AND read_at IS NULL',
                              (g.user['id'], g.family_id)).fetchone()[0]
    for r in rows:
        r['read'] = bool(r.pop('read_at'))
    return jsonify(items=rows, unread=unread)


@bp.post('/notifications/read')
def mark_read():
    """ids: those to mark as read; without ids, all of them."""
    ids = body().get('ids')
    with db.transaction() as conn:
        if isinstance(ids, list):
            for nid in ids[:200]:
                conn.execute("UPDATE notifications SET read_at = datetime('now') WHERE id = ? AND user_id = ? AND read_at IS NULL",
                             (nid, g.user['id']))
        else:
            conn.execute("UPDATE notifications SET read_at = datetime('now') WHERE user_id = ? AND family_id = ? AND read_at IS NULL",
                         (g.user['id'], g.family_id))
    return get_notifications()


# ---------- Web Push ----------

@bp.get('/push/key')
def push_key():
    return jsonify(key=notify.public_key())


def _subscription(d):
    endpoint = str(d.get('endpoint') or '')
    keys = d.get('keys') if isinstance(d.get('keys'), dict) else {}
    p256dh, auth_key = str(keys.get('p256dh') or ''), str(keys.get('auth') or '')
    # Only https endpoints of a push service: never let the server be pointed at arbitrary hosts
    if not endpoint.startswith('https://') or len(endpoint) > 1000 or not urlparse(endpoint).hostname:
        abort(400, 'Invalid subscription')
    if not (0 < len(p256dh) <= 200 and 0 < len(auth_key) <= 100):
        abort(400, 'Invalid subscription')
    return endpoint, p256dh, auth_key


@bp.post('/push/subscriptions')
def subscribe():
    endpoint, p256dh, auth_key = _subscription(body())
    with db.transaction() as conn:
        conn.execute('DELETE FROM push_subscriptions WHERE endpoint = ?', (endpoint,))
        conn.execute('INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (?,?,?,?)',
                     (g.user['id'], endpoint, p256dh, auth_key))
        conn.execute('''DELETE FROM push_subscriptions WHERE user_id = ? AND id NOT IN
                        (SELECT id FROM push_subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT ?)''',
                     (g.user['id'], g.user['id'], MAX_SUBSCRIPTIONS))
        n = conn.execute('SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ?', (g.user['id'],)).fetchone()[0]
    return jsonify(ok=True, devices=n), 201


@bp.delete('/push/subscriptions')
def unsubscribe():
    endpoint = str(body().get('endpoint') or '')
    with db.transaction() as conn:
        conn.execute('DELETE FROM push_subscriptions WHERE endpoint = ? AND user_id = ?', (endpoint, g.user['id']))
    return jsonify(ok=True)


@bp.post('/push/test')
def test_push():
    """A test notification to all the user's devices."""
    with db.transaction() as conn:
        if not conn.execute('SELECT 1 FROM push_subscriptions WHERE user_id = ?', (g.user['id'],)).fetchone():
            abort(400, 'No device with notifications turned on')
    notify.deliver(g.user['id'], {'title': 'doTrack', 'body': i18n.tr('Notifications are working.'), 'url': '/#/agenda', 'tag': 'test'})
    return jsonify(ok=True)
