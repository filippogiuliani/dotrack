"""doTrack's part of the weHub link (the rest is famkit.hub): who this app's people are, what happens when a
member leaves, how two families made separately are merged. Registered in app.py with hub.use(hub_hooks)."""
from flask import jsonify, request

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
