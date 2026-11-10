"""API: family, members and invitations."""
from flask import Blueprint, abort, g, jsonify, session

import db
import hub
import i18n
from auth import app_link, create_token, rate_limit, read_token, require_admin, use_token
from common import body, text

bp = Blueprint('family', __name__)


@bp.get('/family')
def family():
    with db.transaction() as conn:
        f = conn.execute('SELECT id, name, created_at FROM families WHERE id = ?', (g.family_id,)).fetchone()
        members = [dict(r) for r in conn.execute('''SELECT u.id, u.name, u.email, m.role FROM members m JOIN users u ON u.id = m.user_id
                                                    WHERE m.family_id = ? ORDER BY m.created_at''', (g.family_id,))]
        people = [dict(r) for r in conn.execute('SELECT id, name FROM people WHERE family_id = ? ORDER BY name COLLATE NOCASE',
                                                (g.family_id,))]
    for m in members:
        m['me'] = m['id'] == g.user['id']
    return jsonify(**dict(f), members=members, people=people, role=g.role)


# ---------- People without an account (kids, grandparents, babysitter…): any member can manage them ----------

MAX_PEOPLE = 50


def _person_name(conn, exclude=None):
    name = text(body().get('name'), 60)
    if not name:
        abort(400, 'Name is required')
    if conn.execute('SELECT 1 FROM people WHERE family_id = ? AND name = ? COLLATE NOCASE AND id IS NOT ?',
                    (g.family_id, name, exclude)).fetchone():
        abort(409, 'There is already someone with this name')
    return name


@bp.post('/family/people')
def add_person():
    hub.guard()
    with db.transaction() as conn:
        if conn.execute('SELECT COUNT(*) FROM people WHERE family_id = ?', (g.family_id,)).fetchone()[0] >= MAX_PEOPLE:
            abort(400, 'Too many people')
        name = _person_name(conn)
        pid = conn.execute('INSERT INTO people (family_id, name) VALUES (?, ?)', (g.family_id, name)).lastrowid
    return jsonify(id=pid, name=name), 201


def _person(conn, pid):
    if not conn.execute('SELECT 1 FROM people WHERE id = ? AND family_id = ?', (pid, g.family_id)).fetchone():
        abort(404, 'Person not found')


@bp.put('/family/people/<int:pid>')
def rename_person(pid):
    hub.guard()
    with db.transaction() as conn:
        _person(conn, pid)
        name = _person_name(conn, exclude=pid)
        conn.execute('UPDATE people SET name = ? WHERE id = ?', (name, pid))
    return jsonify(id=pid, name=name)


@bp.delete('/family/people/<int:pid>')
def delete_person(pid):
    """Their items go back to "anyone"."""
    hub.guard()
    with db.transaction() as conn:
        _person(conn, pid)
        conn.execute('UPDATE items SET person_id = NULL WHERE person_id = ?', (pid,))
        conn.execute('DELETE FROM people WHERE id = ?', (pid,))
    return jsonify(ok=True)


@bp.put('/family')
def rename():
    hub.guard()
    require_admin()
    name = text(body().get('name'), 80)
    if not name:
        abort(400, 'Name is required')
    with db.transaction() as conn:
        conn.execute('UPDATE families SET name = ? WHERE id = ?', (name, g.family_id))
    return jsonify(ok=True)


@bp.post('/family/switch')
def switch():
    try:
        family_id = int(body().get('family_id'))
    except (TypeError, ValueError):
        abort(400, 'invalid family_id')
    if not any(f['id'] == family_id for f in g.families):
        abort(404, 'Family not found')
    session['family_id'] = family_id
    return jsonify(ok=True)


@bp.post('/family/invites')
def create_invite():
    """Invitation link, valid for 7 days and usable once."""
    hub.guard()
    require_admin()
    rate_limit(f'invite:{g.user["id"]}', 20, 3600)
    with db.transaction() as conn:
        token, expires = create_token(conn, 'invite', 24 * 7, user_id=g.user['id'], family_id=g.family_id)
    return jsonify(link=app_link('invite/' + token), expires_at=expires), 201


@bp.delete('/family/members/<int:uid>')
def remove_member(uid):
    """An admin can remove a member; anyone can leave (uid = their own id)."""
    hub.guard()
    if uid != g.user['id']:
        require_admin()
    with db.transaction() as conn:
        members = conn.execute('SELECT user_id, role FROM members WHERE family_id = ? ORDER BY created_at', (g.family_id,)).fetchall()
        if not any(m['user_id'] == uid for m in members):
            abort(404, 'Member not found')
        others = [m for m in members if m['user_id'] != uid]
        if not others:
            abort(400, "You're the only member: to delete the family, delete your account")
        conn.execute('DELETE FROM members WHERE family_id = ? AND user_id = ?', (g.family_id, uid))
        # Their items go back to "anyone", and their calendar feed stops showing this family
        conn.execute('UPDATE items SET assignee_id = NULL WHERE family_id = ? AND assignee_id = ?', (g.family_id, uid))
        conn.execute('DELETE FROM calendar_feeds WHERE user_id = ? AND family_id = ?', (uid, g.family_id))
        if not any(m['role'] == 'admin' for m in others):
            conn.execute("UPDATE members SET role = 'admin' WHERE family_id = ? AND user_id = ?", (g.family_id, others[0]['user_id']))
        # Whoever leaves their only family gets a new, empty one
        if uid == g.user['id'] and len(g.families) == 1:
            family_id = db.create_family(conn, i18n.tr("{name}'s family", name=g.user['name']), g.user['language'])
            conn.execute("INSERT INTO members (family_id, user_id, role) VALUES (?, ?, 'admin')", (family_id, uid))
            session['family_id'] = family_id
    return jsonify(ok=True)


# ---------- Invitations (public: they can be opened without an account) ----------

@bp.get('/invites/<token>')
def invite_info(token):
    rate_limit(f'invite-info:{token[:12]}', 30, 3600)
    with db.transaction() as conn:
        t = read_token(conn, token, 'invite')
        if not t:
            abort(404, 'Invalid or expired invitation')
        f = conn.execute('SELECT name FROM families WHERE id = ?', (t['family_id'],)).fetchone()
        sender = conn.execute('SELECT name FROM users WHERE id = ?', (t['user_id'],)).fetchone()
    already_member = any(x['id'] == t['family_id'] for x in getattr(g, 'families', []) or [])
    return jsonify(family=f['name'], invited_by=sender['name'] if sender else None, already_member=already_member)


@bp.post('/invites/<token>/accept')
def accept_invite(token):
    hub.guard()
    if not getattr(g, 'user', None):
        abort(401, 'Sign in or sign up to accept')
    with db.transaction() as conn:
        t = read_token(conn, token, 'invite')
        if not t:
            abort(404, 'Invalid or expired invitation')
        conn.execute("INSERT OR IGNORE INTO members (family_id, user_id, role) VALUES (?, ?, 'member')",
                     (t['family_id'], g.user['id']))
        use_token(conn, token)
    session['family_id'] = t['family_id']
    return jsonify(ok=True)
