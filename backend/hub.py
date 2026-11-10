"""weHub link: the family (members, roles, people, who may use this app) is defined in weHub.

Configuration (all optional; without them doTrack works on its own as before):
  DOTRACK_HUB_URL         weHub's address as this server reaches it, e.g. http://wehub:3004
  DOTRACK_HUB_KEY         shared key, the same as WEHUB_APP_DOTRACK_KEY in weHub
  DOTRACK_HUB_PUBLIC_URL  weHub's address for people (links), default DOTRACK_HUB_URL
  DOTRACK_HUB_SYNC_SECONDS how often families are refreshed (default 120)

When on:
- sign-in only through the OIDC provider (the same Pocket ID as weHub); after it weHub says who the person is and
  which families they may use doTrack in. Those families are copied here (members, roles, people).
- the family, its members and people are changed only in weHub: those endpoints answer 409 here.
- families are refreshed every couple of minutes; if weHub is down, people who already signed in go on working.
- weHub reads this app's families once (GET /api/hub/export) to import them, then this app adopts its own rows."""
import hmac
import os
import threading
import time
import traceback

import requests
from flask import Blueprint, abort, jsonify, request

import db

PREFIX = 'DOTRACK'
AGENT = 'doTrack'
URL = os.environ.get(f'{PREFIX}_HUB_URL', '').rstrip('/')
KEY = os.environ.get(f'{PREFIX}_HUB_KEY', '')
PUBLIC_URL = os.environ.get(f'{PREFIX}_HUB_PUBLIC_URL', '').rstrip('/')
INTERVAL = int(os.environ.get(f'{PREFIX}_HUB_SYNC_SECONDS', '120'))
TIMEOUT = 8
NO_PASSWORD = '!'

bp = Blueprint('hub', __name__)


def enabled():
    return bool(URL and KEY)


def guard():
    """For endpoints that change the family: in weHub mode they are not used here."""
    if enabled():
        abort(409, 'The family is managed in weHub')


def public_info():
    return {'url': PUBLIC_URL or URL, 'name': 'weHub'} if enabled() else None


class Unavailable(Exception):
    pass


class NoAccess(Exception):
    pass


def _call(method, path, payload=None):
    try:
        r = requests.request(method, f'{URL}/api/service{path}', json=payload, timeout=TIMEOUT, allow_redirects=False,
                             headers={'Authorization': f'Bearer {KEY}', 'User-Agent': AGENT})
    except requests.RequestException as e:
        raise Unavailable(f'{type(e).__name__}: {e}')
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise Unavailable(f'weHub answered {r.status_code}')
    return r.json()


# ---------- Sign-in ----------

def sign_in(provider, issuer, subject, email, email_verified, name):
    """The local user for someone who just signed in with the provider, their families updated from weHub.
    Raises NoAccess (not in a family that may use this app) or Unavailable (weHub down and never seen before)."""
    try:
        who = _call('POST', '/whoami', {'issuer': issuer, 'subject': subject, 'email': email,
                                        'email_verified': bool(email_verified), 'name': name})
    except Unavailable:
        with db.transaction() as conn:
            u = conn.execute('''SELECT u.* FROM identities i JOIN users u ON u.id = i.user_id
                                WHERE i.provider = ? AND i.subject = ? AND u.hub_id IS NOT NULL''', (provider, subject)).fetchone()
            if u and conn.execute('SELECT 1 FROM members WHERE user_id = ?', (u['id'],)).fetchone():
                return u
        raise
    if not who or not who.get('known') or not who.get('families'):
        raise NoAccess()
    with db.transaction() as conn:
        uid = _user(conn, who['user'])
        keep = {apply_family(conn, snap) for snap in who['families']}
        for (fid,) in conn.execute('''SELECT m.family_id FROM members m JOIN families f ON f.id = m.family_id
                                      WHERE m.user_id = ? AND f.hub_id IS NOT NULL''', (uid,)).fetchall():
            if fid not in keep:
                _remove_member(conn, fid, uid)
        return conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()


def _user(conn, u):
    """Local user id for a weHub user (by weHub id, then by email), created when missing."""
    r = conn.execute('SELECT id FROM users WHERE hub_id = ?', (u['hub_id'],)).fetchone() or \
        conn.execute('SELECT id FROM users WHERE email = ? AND hub_id IS NULL', (u['email'],)).fetchone()
    if r:
        uid = r['id']
        conn.execute('UPDATE users SET hub_id = ?, name = ?, email_verified = 1 WHERE id = ?', (u['hub_id'], u['name'], uid))
        if not conn.execute('SELECT 1 FROM users WHERE email = ? AND id != ?', (u['email'], uid)).fetchone():
            conn.execute('UPDATE users SET email = ? WHERE id = ?', (u['email'], uid))
        return uid
    return conn.execute("INSERT INTO users (email, name, password_hash, email_verified, language, consent_at, hub_id) "
                        "VALUES (?,?,?,1,?,datetime('now'),?)",
                        (u['email'], u['name'], NO_PASSWORD, u.get('language') or 'it', u['hub_id'])).lastrowid


def _remove_member(conn, family_id, user_id):
    conn.execute('DELETE FROM members WHERE family_id = ? AND user_id = ?', (family_id, user_id))
    on_member_removed(conn, family_id, user_id)
    # Signed out everywhere: their next request finds no session
    if not conn.execute('SELECT 1 FROM members WHERE user_id = ?', (user_id,)).fetchone():
        conn.execute('UPDATE users SET session_version = session_version + 1 WHERE id = ?', (user_id,))


def apply_family(conn, snap):
    """Make the local copy of a weHub family match the snapshot. Returns the local family id."""
    f = conn.execute('SELECT id FROM families WHERE hub_id = ?', (snap['hub_id'],)).fetchone()
    if not f and snap.get('local_id'):
        f = conn.execute('SELECT id FROM families WHERE id = ? AND hub_id IS NULL', (snap['local_id'],)).fetchone()
    if f:
        fid = f['id']
        conn.execute('UPDATE families SET hub_id = ?, hub_version = ?, name = ? WHERE id = ?',
                     (snap['hub_id'], snap['version'], snap['name'], fid))
    else:
        lang = next((m.get('language') for m in snap['members'] if m.get('language')), 'it')
        fid = db.create_family(conn, snap['name'], lang)
        conn.execute('UPDATE families SET hub_id = ?, hub_version = ? WHERE id = ?', (snap['hub_id'], snap['version'], fid))
    wanted = {}
    for m in snap['members']:
        uid = _user(conn, m)
        wanted[uid] = m['role']
        conn.execute('INSERT INTO members (family_id, user_id, role) VALUES (?,?,?) '
                     'ON CONFLICT(family_id, user_id) DO UPDATE SET role = excluded.role', (fid, uid, m['role']))
    for (uid,) in conn.execute('SELECT user_id FROM members WHERE family_id = ?', (fid,)).fetchall():
        if uid not in wanted:
            _remove_member(conn, fid, uid)
    apply_people(conn, fid, snap)
    bump(conn, fid)
    return fid


# ---------- Periodic refresh ----------

def sync_all():
    with db.transaction() as conn:
        fams = conn.execute('SELECT id, hub_id, hub_version FROM families WHERE hub_id IS NOT NULL').fetchall()
    for f in fams:
        snap = _call('GET', f"/families/{f['hub_id']}?version={f['hub_version'] or ''}")
        if snap is None:
            print(f"[hub] family {f['hub_id']} no longer exists in weHub: local copy kept as it is", flush=True)
            continue
        if snap.get('unchanged'):
            continue
        with db.transaction() as conn:
            apply_family(conn, snap)


def start_sync():
    if not enabled():
        return

    def loop():
        while True:
            time.sleep(INTERVAL)
            try:
                sync_all()
            except Unavailable as e:
                print(f'[hub] weHub not reachable: {e}', flush=True)
            except Exception:
                traceback.print_exc()

    threading.Thread(target=loop, daemon=True, name='hub-sync').start()
    print(f'[hub] family managed in weHub ({URL}), refreshed every {INTERVAL}s', flush=True)


# ---------- For weHub: what this app has (import) ----------

@bp.get('/hub/export')
def export():
    presented = request.headers.get('Authorization', '')[7:].strip()
    if not KEY or not hmac.compare_digest(KEY, presented):
        return jsonify(error='Unknown key'), 401
    out = []
    with db.transaction() as conn:
        for f in conn.execute('SELECT id, name, hub_id FROM families ORDER BY id').fetchall():
            members = [{'email': r['email'], 'name': r['name'], 'role': r['role']} for r in conn.execute(
                'SELECT u.email, u.name, m.role FROM members m JOIN users u ON u.id = m.user_id WHERE m.family_id = ?', (f['id'],))]
            out.append({'local_id': f['id'], 'name': f['name'], 'hub_id': f['hub_id'], 'members': members,
                        'people': export_people(conn, f['id'])})
    return jsonify(families=out)


# ---------- For weHub: merging families made separately before weHub ----------

@bp.post('/hub/merge')
def merge():
    """{into: local family id, families: [local family ids]}: move everything of those families into `into`.
    Called by weHub's import when two people had made separate families before. A backup of the database is made
    first; nothing is deleted except the emptied families (checked: if any row still belongs to one, nothing is done)."""
    presented = request.headers.get('Authorization', '')[7:].strip()
    if not KEY or not hmac.compare_digest(KEY, presented):
        return jsonify(error='Unknown key'), 401
    d = request.get_json(silent=True) or {}
    try:
        into = int(d.get('into'))
        sources = sorted({int(x) for x in d.get('families') or []} - {into})
    except (TypeError, ValueError):
        return jsonify(error='Invalid request'), 400
    if not sources:
        return jsonify(error='Nothing to merge'), 400
    with db.transaction() as conn:
        found = {r['id']: r for r in conn.execute(
            f"SELECT id, hub_id FROM families WHERE id IN ({','.join('?' * (len(sources) + 1))})", (into, *sources))}
        if into not in found or any(s not in found for s in sources):
            return jsonify(error='Family not found'), 404
        if any(found[s]['hub_id'] for s in sources):
            return jsonify(error='A family linked to weHub cannot be merged into another'), 409
    import backup
    backup.create_backup('pre-merge')
    report = {}
    try:
        with db.transaction() as conn:
            for src in sources:
                merge_family(conn, src, into, report)
            bump(conn, into)
    except RuntimeError as e:
        print(f'[hub] merge cancelled: {e}', flush=True)
        return jsonify(error=str(e)), 409
    print(f'[hub] merged families {sources} into {into}: {report}', flush=True)
    return jsonify(merged=sources, into=into, report=report)


def merge_family(conn, src, dst, report):
    """Move one family into another inside the caller's transaction."""
    merge_data(conn, src, dst, report)
    # Members: everyone of both families stays (a role already held in the destination wins)
    for m in conn.execute('SELECT user_id, role FROM members WHERE family_id = ?', (src,)).fetchall():
        conn.execute('INSERT OR IGNORE INTO members (family_id, user_id, role) VALUES (?,?,?)', (dst, m['user_id'], m['role']))
    conn.execute('DELETE FROM members WHERE family_id = ?', (src,))
    conn.execute("DELETE FROM tokens WHERE family_id = ?", (src,))  # pending invitations of the old family
    # Safety net: no table may still hold rows of the old family, otherwise deleting it would cascade
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'families'")]
    left = [t for t in tables if 'family_id' in {c[1] for c in conn.execute(f'PRAGMA table_info({t})')}
            and conn.execute(f'SELECT 1 FROM {t} WHERE family_id = ? LIMIT 1', (src,)).fetchone()]
    if left:
        raise RuntimeError(f'family {src} still has rows in {left}: merge cancelled')
    conn.execute('DELETE FROM families WHERE id = ?', (src,))
    report['families'] = report.get('families', 0) + 1


def _count(report, key, n):
    if n:
        report[key] = report.get(key, 0) + n


# ======================================================================
# This app's people: people without an account, to put in charge of things
# ======================================================================

def bump(conn, family_id):
    db.bump(conn, family_id)


def apply_people(conn, family_id, snap):
    """weHub people who are not doTrack members become doTrack "people" (kids, grandparents, the babysitter…)."""
    member_hub_ids = {m['hub_id'] for m in snap['members']}
    wanted = [p for p in snap['people'] if p.get('user_hub_id') not in member_hub_ids or p.get('user_hub_id') is None]
    seen = set()
    for p in wanted:
        r = conn.execute('SELECT id FROM people WHERE family_id = ? AND hub_id = ?', (family_id, p['hub_id'])).fetchone()
        if not r and p.get('local_id'):
            r = conn.execute('SELECT id FROM people WHERE family_id = ? AND id = ? AND hub_id IS NULL', (family_id, p['local_id'])).fetchone()
        if not r:
            r = conn.execute('SELECT id FROM people WHERE family_id = ? AND name = ? COLLATE NOCASE AND hub_id IS NULL',
                             (family_id, p['name'])).fetchone()
        if r:
            conn.execute('UPDATE people SET hub_id = ?, name = ? WHERE id = ?', (p['hub_id'], p['name'], r['id']))
            seen.add(r['id'])
        else:
            seen.add(conn.execute('INSERT INTO people (family_id, name, hub_id) VALUES (?,?,?)',
                                  (family_id, p['name'], p['hub_id'])).lastrowid)
    for (pid,) in conn.execute('SELECT id FROM people WHERE family_id = ? AND hub_id IS NOT NULL', (family_id,)).fetchall():
        if pid not in seen:
            # Removed in weHub: their things go back to "anyone"
            conn.execute('UPDATE items SET person_id = NULL WHERE person_id = ?', (pid,))
            conn.execute('DELETE FROM people WHERE id = ?', (pid,))


def export_people(conn, family_id):
    return [{'local_id': r['id'], 'name': r['name'], 'kind': 'adult'}
            for r in conn.execute('SELECT id, name FROM people WHERE family_id = ?', (family_id,))]


def on_member_removed(conn, family_id, user_id):
    conn.execute('UPDATE items SET assignee_id = NULL WHERE family_id = ? AND assignee_id = ?', (family_id, user_id))
    conn.execute('DELETE FROM calendar_feeds WHERE user_id = ? AND family_id = ?', (user_id, family_id))
    conn.execute('DELETE FROM api_tokens WHERE user_id = ? AND family_id = ?', (user_id, family_id))


def merge_data(conn, src, dst, report):
    """doTrack: people and labels with the same name become one; lists, to-dos, notifications and keys move."""
    for p in conn.execute('SELECT id, name FROM people WHERE family_id = ?', (src,)).fetchall():
        t = conn.execute('SELECT id FROM people WHERE family_id = ? AND name = ? COLLATE NOCASE', (dst, p['name'])).fetchone()
        if t:
            conn.execute('UPDATE items SET person_id = ? WHERE person_id = ?', (t['id'], p['id']))
            conn.execute('DELETE FROM people WHERE id = ?', (p['id'],))
            _count(report, 'people_merged', 1)
        else:
            conn.execute('UPDATE people SET family_id = ? WHERE id = ?', (dst, p['id']))
    for lb in conn.execute('SELECT id, name FROM labels WHERE family_id = ?', (src,)).fetchall():
        t = conn.execute('SELECT id FROM labels WHERE family_id = ? AND name = ? COLLATE NOCASE', (dst, lb['name'])).fetchone()
        if t:
            conn.execute('UPDATE OR IGNORE item_labels SET label_id = ? WHERE label_id = ?', (t['id'], lb['id']))
            conn.execute('DELETE FROM item_labels WHERE label_id = ?', (lb['id'],))
            conn.execute('DELETE FROM labels WHERE id = ?', (lb['id'],))
            _count(report, 'labels_merged', 1)
        else:
            conn.execute('UPDATE labels SET family_id = ? WHERE id = ?', (dst, lb['id']))
    _count(report, 'lists', conn.execute('UPDATE lists SET family_id = ? WHERE family_id = ?', (dst, src)).rowcount)
    # Names given by CalDAV clients must stay unique inside a family
    conn.execute('''UPDATE items SET caldav_name = NULL WHERE family_id = ? AND caldav_name IN
                    (SELECT caldav_name FROM items WHERE family_id = ? AND caldav_name IS NOT NULL)''', (src, dst))
    _count(report, 'items', conn.execute('UPDATE items SET family_id = ? WHERE family_id = ?', (dst, src)).rowcount)
    for table in ('notifications', 'calendar_feeds', 'api_tokens', 'webhooks'):
        conn.execute(f'UPDATE {table} SET family_id = ? WHERE family_id = ?', (dst, src))
