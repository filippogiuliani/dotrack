"""doTrack's part of the weHub link (the rest is famkit.hub): who this app's people are, what happens when a
member leaves, how two families made separately are merged. Registered in app.py with hub.use(hub_hooks)."""
import re

from flask import abort, g, jsonify, request

import db
from famkit import hub

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
            hub.count(report, 'people_merged', 1)
        else:
            conn.execute('UPDATE people SET family_id = ? WHERE id = ?', (dst, p['id']))
    for lb in conn.execute('SELECT id, name FROM labels WHERE family_id = ?', (src,)).fetchall():
        t = conn.execute('SELECT id FROM labels WHERE family_id = ? AND name = ? COLLATE NOCASE', (dst, lb['name'])).fetchone()
        if t:
            conn.execute('UPDATE OR IGNORE item_labels SET label_id = ? WHERE label_id = ?', (t['id'], lb['id']))
            conn.execute('DELETE FROM item_labels WHERE label_id = ?', (lb['id'],))
            conn.execute('DELETE FROM labels WHERE id = ?', (lb['id'],))
            hub.count(report, 'labels_merged', 1)
        else:
            conn.execute('UPDATE labels SET family_id = ? WHERE id = ?', (dst, lb['id']))
    hub.count(report, 'lists', conn.execute('UPDATE lists SET family_id = ? WHERE family_id = ?', (dst, src)).rowcount)
    # Names given by CalDAV clients must stay unique inside a family
    conn.execute('''UPDATE items SET caldav_name = NULL WHERE family_id = ? AND caldav_name IN
                    (SELECT caldav_name FROM items WHERE family_id = ? AND caldav_name IS NOT NULL)''', (src, dst))
    hub.count(report, 'items', conn.execute('UPDATE items SET family_id = ? WHERE family_id = ?', (dst, src)).rowcount)
    for table in ('notifications', 'calendar_feeds', 'api_tokens', 'webhooks'):
        conn.execute(f'UPDATE {table} SET family_id = ? WHERE family_id = ?', (dst, src))


# ======================================================================
# For the other family apps, through weHub (see famkit.hub.service)
# ======================================================================

@hub.service('/lists')
def service_lists():
    """eaTrack: the family's shopping lists (to send the weekly menu's foods)."""
    from api_lists import checklists
    with db.transaction() as conn:
        return jsonify(checklists(conn))


@hub.service('/lists/<int:list_id>/items', methods=['POST'])
def service_add_items(list_id):
    """{items: ["latte", …]} → {added: [...], skipped: [...]} (already on the list: skipped)."""
    from api_lists import add_entries
    added, skipped = add_entries(list_id, (request.get_json(silent=True) or {}).get('items'))
    return jsonify(added=added, skipped=skipped), 201


# ---------- paTrack: deadlines of documents (identity card, licence, warranty…) ----------
# paTrack decides: when someone asks for it on a document with an expiry date, paTrack puts the deadline here and keeps
# it in step (date, reminder, who it is about, link to the document). What people add in doTrack (labels, notes,
# priority, a repetition) stays. A deadline deleted here is not created again: paTrack is told and stops.

PATRACK_CATEGORIES = {'identity': 'documents', 'health': 'health', 'child': 'kids', 'home': 'home', 'car': 'car',
                      'tax': 'money', 'work': 'work', 'purchases': 'documents', 'bank': 'money', 'insurance': 'money'}
REF = re.compile(r'patrack-\d+')


def in_charge(conn, d):
    """(assignee_id, person_id) from the weHub ids another app sends: a member, or a person without an account."""
    if d.get('member_hub_id'):
        r = conn.execute('SELECT u.id FROM users u JOIN members m ON m.user_id = u.id AND m.family_id = ? WHERE u.hub_id = ?',
                         (g.family_id, d['member_hub_id'])).fetchone()
        if r:
            return r['id'], None
    if d.get('person_hub_id'):
        r = conn.execute('SELECT id FROM people WHERE family_id = ? AND hub_id = ?', (g.family_id, d['person_hub_id'])).fetchone()
        if r:
            return None, r['id']
    return None, None


def hub_ids_of(conn, assignee_id, person_id):
    """The other way round: {member_hub_id} or {person_hub_id} for an item's assignee or person."""
    if assignee_id:
        r = conn.execute('SELECT hub_id FROM users WHERE id = ?', (assignee_id,)).fetchone()
        return {'member_hub_id': r['hub_id']} if r and r['hub_id'] else {}
    if person_id:
        r = conn.execute('SELECT hub_id FROM people WHERE id = ?', (person_id,)).fetchone()
        return {'person_hub_id': r['hub_id']} if r and r['hub_id'] else {}
    return {}


def _url(value):
    v = str(value or '')[:500]
    return v if v.startswith(('https://', 'http://')) else None


@hub.service('/deadlines/<ref>', methods=['PUT'])
def put_deadline(ref):
    """{title, due_date, remind_days, category, notes, url, member_hub_id | person_hub_id} → {item_id, created | deleted}"""
    import api_items
    if not REF.fullmatch(ref):
        abort(400, 'Invalid request')
    d = request.get_json(silent=True) or {}
    with db.transaction() as conn:
        assignee_id, person_id = in_charge(conn, d)
        wanted = {'kind': 'deadline', 'title': d.get('title'), 'due_date': d.get('due_date'), 'remind_days': d.get('remind_days'),
                  'category': PATRACK_CATEGORIES.get(d.get('category'), 'documents'), 'notes': d.get('notes') or '',
                  'assignee_id': assignee_id, 'person_id': person_id}
        if not wanted['due_date']:
            abort(400, 'A date is required')
        cur = conn.execute('SELECT * FROM items WHERE family_id = ? AND ext_ref = ?', (g.family_id, ref)).fetchone()
        if cur and cur['deleted_at']:
            return jsonify(item_id=cur['id'], deleted=True)
        if not cur:
            item = api_items.insert_item(conn, wanted)
            conn.execute('UPDATE items SET ext_ref = ?, ext_url = ? WHERE id = ?', (ref, _url(d.get('url')), item['id']))
            return jsonify(item_id=item['id'], created=True), 201
        f = api_items.fields(conn, wanted)
        mine = {k: f[k] for k in ('title', 'due_date', 'remind_days', 'assignee_id', 'person_id')}
        if mine['remind_days'] is None:
            mine['remind_time'] = None
        mine['ext_url'] = _url(d.get('url')) or cur['ext_url']
        if any(cur[k] != v for k, v in mine.items()):
            conn.execute(f"UPDATE items SET {', '.join(k + ' = ?' for k in mine)}, updated_at = datetime('now') WHERE id = ?",
                         (*mine.values(), cur['id']))
            api_items.log(conn, cur['id'], 'updated')
            if cur['done_at'] and mine['due_date'] != cur['due_date']:
                api_items.reopen_item(conn, cur['id'], g.family_id)   # renewed document, new expiry: open again
        return jsonify(item_id=cur['id'], created=False)


@hub.service('/deadlines/<ref>', methods=['DELETE'])
def delete_deadline(ref):
    """The document went to the trash, lost its expiry date or no longer wants it: the deadline goes to the trash."""
    import api_items
    if not REF.fullmatch(ref):
        abort(400, 'Invalid request')
    with db.transaction() as conn:
        cur = conn.execute('SELECT id FROM items WHERE family_id = ? AND ext_ref = ? AND deleted_at IS NULL',
                           (g.family_id, ref)).fetchone()
        if cur:
            api_items.trash_item(conn, cur['id'])
            # The reference is freed: asked again later, the document gets a new deadline (not this one restored)
            conn.execute('UPDATE items SET ext_ref = NULL WHERE id = ?', (cur['id'],))
    return jsonify(ok=True)
