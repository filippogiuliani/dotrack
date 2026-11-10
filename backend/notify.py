"""Notifications: kept in the database (the bell in the app) and pushed to the user's devices (Web Push).

Push needs no external account: the server signs messages with its own VAPID key, created on first use
in DATA_DIR/.vapid_private.pem. Browsers deliver them through their vendor's push service."""
import base64
import json
import os
import threading

import db

MAX_PER_USER = 200  # older notifications are dropped
_key_lock = threading.Lock()


# ---------- VAPID key ----------

def _key_path():
    return os.path.join(db.DATA_DIR, '.vapid_private.pem')


def vapid():
    """The server's VAPID key (py_vapid.Vapid), created on first use."""
    from py_vapid import Vapid
    path = _key_path()
    with _key_lock:
        if not os.path.exists(path):
            os.makedirs(db.DATA_DIR, exist_ok=True)
            v = Vapid()
            v.generate_keys()
            v.save_key(path)
            os.chmod(path, 0o600)
    return Vapid.from_file(path)


def public_key():
    """Public key for the browser (applicationServerKey): base64url of the uncompressed point."""
    from cryptography.hazmat.primitives import serialization
    raw = vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _contact():
    from auth import BASE_URL
    sender = os.environ.get('DOTRACK_MAIL_FROM', '')
    if '<' in sender and '>' in sender:
        sender = sender.split('<', 1)[1].split('>', 1)[0]
    if '@' in sender:
        return 'mailto:' + sender.strip()
    return BASE_URL if BASE_URL.startswith('https://') else 'mailto:admin@localhost'


# ---------- Push ----------

def send_push(conn, user_id, payload):
    """Send `payload` (dict) to every device of the user. Subscriptions the push service says are gone are removed.
    Returns how many deliveries succeeded."""
    subs = conn.execute('SELECT * FROM push_subscriptions WHERE user_id = ?', (user_id,)).fetchall()
    if not subs:
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:  # optional dependency missing: in-app notifications still work
        return 0
    key, sent = vapid(), 0
    for s in subs:
        try:
            webpush({'endpoint': s['endpoint'], 'keys': {'p256dh': s['p256dh'], 'auth': s['auth']}},
                    data=json.dumps(payload), vapid_private_key=key, vapid_claims={'sub': _contact()}, ttl=86400, timeout=10)
            sent += 1
        except WebPushException as e:
            status = getattr(e.response, 'status_code', None)
            if status in (404, 410):  # unsubscribed or expired
                conn.execute('DELETE FROM push_subscriptions WHERE id = ?', (s['id'],))
            else:
                print(f'[push] {status}: {e}', flush=True)
        except Exception as e:  # network errors must never break the request
            print(f'[push] error: {e}', flush=True)
    return sent


# Pushes are sent after the request's transaction, in a background thread, so a slow push service
# never delays the app. Tests replace `deliver` to capture them.
def deliver(user_id, payload):
    def run():
        try:
            with db.transaction() as conn:
                send_push(conn, user_id, payload)
        except Exception as e:
            print(f'[push] error: {e}', flush=True)
    threading.Thread(target=run, daemon=True).start()


# ---------- Notifications ----------

def notify(conn, user_id, family_id, kind, title, body='', item_id=None, actor_id=None, push=True):
    """Store a notification for `user_id` and push it to their devices."""
    nid = conn.execute('''INSERT INTO notifications (user_id, family_id, item_id, actor_id, kind, title, body)
                          VALUES (?,?,?,?,?,?,?)''', (user_id, family_id, item_id, actor_id, kind, title[:200], body[:500])).lastrowid
    conn.execute('''DELETE FROM notifications WHERE user_id = ? AND id NOT IN
                    (SELECT id FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?)''', (user_id, user_id, MAX_PER_USER))
    if push:
        url = f'/#/item/{item_id}' if item_id else '/#/agenda'
        deliver(user_id, {'title': title, 'body': body, 'url': url, 'tag': f'{kind}-{item_id or nid}', 'id': nid})
    return nid


def family_users(conn, family_id):
    return [r[0] for r in conn.execute('SELECT user_id FROM members WHERE family_id = ?', (family_id,))]


def concerned(conn, item):
    """Users an item is for: its assignee, or everyone in the family when it is for "anyone" or for a person
    without an account."""
    if item['assignee_id']:
        return [item['assignee_id']]
    return family_users(conn, item['family_id'])


def language_of(conn, user_id):
    r = conn.execute('SELECT language FROM users WHERE id = ?', (user_id,)).fetchone()
    return r[0] if r else 'it'


def when_text(item, lang):
    """"12/11/2026 15:30" for the notification body, '' without a date."""
    import datetime
    import i18n
    if not item['due_date']:
        return ''
    d = datetime.date.fromisoformat(item['due_date'])
    today = datetime.date.today()
    if d == today:
        out = i18n.tr('Today', lang)
    elif d == today + datetime.timedelta(days=1):
        out = i18n.tr('Tomorrow', lang)
    else:
        out = d.strftime('%d/%m/%Y')
    if item['due_time']:
        out += ' ' + item['due_time']
    return out
