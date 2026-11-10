"""Outgoing webhooks: on each change the family's endpoints get a JSON POST, signed with HMAC-SHA256
(header X-doTrack-Signature: sha256=<hex of the body with the webhook's secret>)."""
import datetime
import hashlib
import hmac
import json
import threading

import db

TIMEOUT = 8


def _post(hook_id, url, secret, body):
    import requests
    sig = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    try:
        r = requests.post(url, data=body, timeout=TIMEOUT, allow_redirects=False,
                          headers={'Content-Type': 'application/json', 'X-doTrack-Signature': sig, 'User-Agent': 'doTrack-webhook'})
        status = str(r.status_code)
    except Exception as e:
        status = 'error: ' + type(e).__name__
    try:
        with db.transaction() as conn:
            conn.execute("UPDATE webhooks SET last_status = ?, last_at = datetime('now') WHERE id = ?", (status, hook_id))
    except Exception:
        pass
    return status


def send(hooks):
    """[(id, url, secret, body)] → posted in a background thread. Tests replace this."""
    def run():
        for h in hooks:
            _post(*h)
    threading.Thread(target=run, daemon=True).start()


def emit(conn, family_id, event, data, actor_id=None):
    """Queue `event` for the family's webhooks that listen to it."""
    hooks = []
    body = json.dumps({'event': event, 'family_id': family_id, 'actor_id': actor_id,
                       'at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'data': data},
                      ensure_ascii=False, default=str).encode()
    for h in conn.execute('SELECT id, url, secret, events FROM webhooks WHERE family_id = ?', (family_id,)):
        if event in h['events'].split(','):
            hooks.append((h['id'], h['url'], h['secret'], body))
    if hooks:
        send(hooks)
