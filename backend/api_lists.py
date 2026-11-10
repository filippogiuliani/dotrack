"""API: lists (shopping list, packing list…), projects and labels. One level only: no nested lists."""
from flask import Blueprint, abort, g, jsonify

import db
import shopping
from api_items import _load, delete_items, insert_item, next_color, remove_files
from common import body, text

bp = Blueprint('lists', __name__)

MAX_LISTS = 100
MAX_LABELS_PER_FAMILY = 200


def _color(value, default):
    c = value or default
    if c not in db.COLORS:
        abort(400, 'Invalid colour')
    return c


# ---------- Lists ----------

def _lists(conn):
    rows = conn.execute('''SELECT l.*,
                             (SELECT COUNT(*) FROM items i WHERE i.list_id = l.id AND i.done_at IS NULL AND i.deleted_at IS NULL) AS open_count,
                             (SELECT COUNT(*) FROM items i WHERE i.list_id = l.id AND i.done_at IS NOT NULL AND i.deleted_at IS NULL) AS done_count
                           FROM lists l WHERE l.family_id = ? ORDER BY l.archived, l.position, l.id''', (g.family_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d['archived'] = bool(d['archived'])
        d['sections'] = bool(d['sections'])
        d['template'] = bool(d['template'])
        del d['family_id']
        out.append(d)
    return out


def _list(conn, list_id):
    r = conn.execute('SELECT * FROM lists WHERE id = ? AND family_id = ?', (list_id, g.family_id)).fetchone()
    if not r:
        abort(404, 'List not found')
    return r


def _list_fields(d, current=None):
    name = text(d.get('name', current['name'] if current else ''), 60)
    if not name:
        abort(400, 'Name is required')
    kind = d.get('kind', current['kind'] if current else 'checklist')
    if kind not in db.LIST_KINDS:
        abort(400, 'Invalid type')
    keep = lambda k: bool(current[k]) if current else False
    return {'name': name, 'kind': kind, 'color': _color(d.get('color'), current['color'] if current else 'blue'),
            'archived': 1 if d.get('archived', keep('archived')) else 0,
            'sections': 1 if d.get('sections', keep('sections')) and kind == 'checklist' else 0,
            'template': 1 if d.get('template', keep('template')) else 0}


@bp.get('/lists')
def get_lists():
    with db.transaction() as conn:
        return jsonify(_lists(conn))


@bp.post('/lists')
def create_list():
    with db.transaction() as conn:
        if conn.execute('SELECT COUNT(*) FROM lists WHERE family_id = ?', (g.family_id,)).fetchone()[0] >= MAX_LISTS:
            abort(400, 'Too many lists')
        f = _list_fields(body())
        pos = conn.execute('SELECT COALESCE(MAX(position), 0) + 1 FROM lists WHERE family_id = ?', (g.family_id,)).fetchone()[0]
        lid = conn.execute('INSERT INTO lists (family_id, name, kind, color, archived, sections, template, position) VALUES (?,?,?,?,?,?,?,?)',
                           (g.family_id, f['name'], f['kind'], f['color'], f['archived'], f['sections'], f['template'], pos)).lastrowid
        return jsonify(next(x for x in _lists(conn) if x['id'] == lid)), 201


@bp.put('/lists/<int:list_id>')
def update_list(list_id):
    with db.transaction() as conn:
        f = _list_fields(body(), _list(conn, list_id))
        conn.execute('UPDATE lists SET name = ?, kind = ?, color = ?, archived = ?, sections = ?, template = ? WHERE id = ?',
                     (f['name'], f['kind'], f['color'], f['archived'], f['sections'], f['template'], list_id))
        return jsonify(next(x for x in _lists(conn) if x['id'] == list_id))


@bp.put('/lists/order')
def order_lists():
    """ids: the family's lists in the new order."""
    ids = body().get('ids')
    if not isinstance(ids, list):
        abort(400, 'Invalid request (JSON expected)')
    with db.transaction() as conn:
        for pos, lid in enumerate(ids):
            conn.execute('UPDATE lists SET position = ? WHERE id = ? AND family_id = ?', (pos, lid, g.family_id))
        return jsonify(_lists(conn))


@bp.delete('/lists/<int:list_id>')
def delete_list(list_id):
    """Deletes the list with everything in it."""
    with db.transaction() as conn:
        _list(conn, list_id)
        stored = delete_items(conn, 'list_id = ? AND family_id = ?', (list_id, g.family_id))
        conn.execute('DELETE FROM lists WHERE id = ?', (list_id,))
    remove_files(stored)
    return jsonify(ok=True)


@bp.post('/lists/<int:list_id>/copy')
def copy_list(list_id):
    """A new list with the same entries, all to do: duplicate, save as a template (template=true)
    or start a list from a template. Dates are not copied."""
    d = body()
    with db.transaction() as conn:
        src = _list(conn, list_id)
        if conn.execute('SELECT COUNT(*) FROM lists WHERE family_id = ?', (g.family_id,)).fetchone()[0] >= MAX_LISTS:
            abort(400, 'Too many lists')
        name = text(d.get('name'), 60) or src['name']
        pos = conn.execute('SELECT COALESCE(MAX(position), 0) + 1 FROM lists WHERE family_id = ?', (g.family_id,)).fetchone()[0]
        new_id = conn.execute('INSERT INTO lists (family_id, name, kind, color, sections, template, position) VALUES (?,?,?,?,?,?,?)',
                              (g.family_id, name, src['kind'], src['color'], src['sections'], 1 if d.get('template') else 0, pos)).lastrowid
        items = _load(conn, 'i.list_id = ?', (list_id,), order='i.position, i.id')
        if not src['template']:
            items = [i for i in items if not i['done']] or items  # a list being copied: what is still open
        for i in items:
            cur = conn.execute('''INSERT INTO items (family_id, created_by, list_id, kind, title, notes, category, subject, assignee_id,
                                  person_id, priority, quantity, section, position) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                               (g.family_id, g.user['id'], new_id, i['kind'] if i['kind'] in ('task', 'deadline') else 'task',
                                i['title'], i['notes'], i['category'], i['subject'], i['assignee_id'], i['person_id'], i['priority'],
                                i['quantity'], i['section'], i['position']))
            for pos_c, c in enumerate(i['checks']):
                conn.execute('INSERT INTO item_checks (item_id, position, text) VALUES (?,?,?)', (cur.lastrowid, pos_c, c['text']))
            for lid in i['labels']:
                conn.execute('INSERT INTO item_labels (item_id, label_id) VALUES (?,?)', (cur.lastrowid, lid))
        conn.execute('''INSERT INTO list_history (list_id, key, name, section, uses, last_used)
                        SELECT ?, key, name, section, uses, last_used FROM list_history WHERE list_id = ?''', (new_id, list_id))
        return jsonify(next(x for x in _lists(conn) if x['id'] == new_id)), 201


@bp.put('/lists/<int:list_id>/items/order')
def order_items(list_id):
    """ids: the list's entries in the new order (manual order, e.g. the way through the shop)."""
    ids = body().get('ids')
    if not isinstance(ids, list):
        abort(400, 'Invalid request (JSON expected)')
    with db.transaction() as conn:
        _list(conn, list_id)
        for pos, iid in enumerate(ids[:1000]):
            conn.execute('UPDATE items SET position = ? WHERE id = ? AND list_id = ? AND family_id = ?', (pos, iid, list_id, g.family_id))
    return jsonify(ok=True)


@bp.get('/lists/<int:list_id>/suggestions')
def suggestions(list_id):
    """What was put in this list before, most used first, except what is already on it."""
    with db.transaction() as conn:
        _list(conn, list_id)
        open_now = {shopping.key(r[0]) for r in conn.execute(
            'SELECT title FROM items WHERE list_id = ? AND done_at IS NULL AND deleted_at IS NULL', (list_id,))}
        rows = conn.execute('''SELECT name, section, uses FROM list_history WHERE list_id = ?
                               ORDER BY uses DESC, last_used DESC LIMIT 300''', (list_id,)).fetchall()
    return jsonify([{'name': r['name'], 'section': r['section'], 'uses': r['uses']} for r in rows
                    if shopping.key(r['name']) not in open_now])


@bp.post('/lists/<int:list_id>/items')
def add_many(list_id):
    """Add several things at once (integrations: eaTrack, Home Assistant, scripts).
    items: ["latte", "2 kg mele", {"title": "pane", "quantity": "1"}]. What is already on the list (not ticked) is skipped."""
    entries = body().get('items')
    if not isinstance(entries, list) or not entries or len(entries) > 200:
        abort(400, 'Invalid request (JSON expected)')
    added, skipped = [], []
    with db.transaction() as conn:
        lst = _list(conn, list_id)
        open_now = {shopping.key(r[0]) for r in conn.execute(
            'SELECT title FROM items WHERE list_id = ? AND done_at IS NULL AND deleted_at IS NULL', (list_id,))}
        for e in entries:
            if isinstance(e, str):
                title, qty = shopping.split_quantity(e) if lst['kind'] == 'checklist' else (e, '')
                e = {'title': title, 'quantity': qty}
            if not isinstance(e, dict) or not text(e.get('title'), 200):
                abort(400, 'Title is required')
            title = text(e['title'], 200)
            if shopping.key(title) in open_now:
                skipped.append(title)
                continue
            open_now.add(shopping.key(title))
            added.append(insert_item(conn, {'kind': 'task', 'category': 'shopping' if lst['kind'] == 'checklist' else 'home',
                                            **{k: e[k] for k in ('quantity', 'notes', 'section', 'due_date', 'priority') if k in e},
                                            'title': title, 'list_id': list_id}))
    return jsonify(added=added, skipped=skipped), 201


@bp.post('/lists/<int:list_id>/clear-done')
def clear_done(list_id):
    """Remove the ticked entries (e.g. what was bought)."""
    with db.transaction() as conn:
        _list(conn, list_id)
        where, params = 'list_id = ? AND family_id = ? AND done_at IS NOT NULL AND deleted_at IS NULL', (list_id, g.family_id)
        removed = conn.execute(f'SELECT COUNT(*) FROM items WHERE {where}', params).fetchone()[0]
        stored = delete_items(conn, where, params)
    remove_files(stored)
    return jsonify(removed=removed)


# ---------- Labels ----------

def _labels(conn):
    return [dict(r) for r in conn.execute(
        '''SELECT l.id, l.name, l.color, (SELECT COUNT(*) FROM item_labels il WHERE il.label_id = l.id) AS count
           FROM labels l WHERE l.family_id = ? ORDER BY l.name COLLATE NOCASE''', (g.family_id,))]


def _label_name(conn, d, exclude=None):
    name = text(d.get('name'), 40).lstrip('#*').strip()
    if not name:
        abort(400, 'Name is required')
    if conn.execute('SELECT 1 FROM labels WHERE family_id = ? AND name = ? COLLATE NOCASE AND id IS NOT ?',
                    (g.family_id, name, exclude)).fetchone():
        abort(409, 'A label with this name already exists')
    return name


@bp.get('/labels')
def get_labels():
    with db.transaction() as conn:
        return jsonify(_labels(conn))


@bp.post('/labels')
def create_label():
    d = body()
    with db.transaction() as conn:
        if conn.execute('SELECT COUNT(*) FROM labels WHERE family_id = ?', (g.family_id,)).fetchone()[0] >= MAX_LABELS_PER_FAMILY:
            abort(400, 'Too many labels')
        name = _label_name(conn, d)
        lid = conn.execute('INSERT INTO labels (family_id, name, color) VALUES (?,?,?)',
                           (g.family_id, name, _color(d.get('color'), next_color(conn)))).lastrowid
        return jsonify(next(x for x in _labels(conn) if x['id'] == lid)), 201


@bp.put('/labels/<int:label_id>')
def update_label(label_id):
    d = body()
    with db.transaction() as conn:
        cur = conn.execute('SELECT * FROM labels WHERE id = ? AND family_id = ?', (label_id, g.family_id)).fetchone()
        if not cur:
            abort(404, 'Label not found')
        name = _label_name(conn, {'name': d.get('name', cur['name'])}, exclude=label_id)
        conn.execute('UPDATE labels SET name = ?, color = ? WHERE id = ?', (name, _color(d.get('color'), cur['color']), label_id))
        return jsonify(next(x for x in _labels(conn) if x['id'] == label_id))


@bp.delete('/labels/<int:label_id>')
def delete_label(label_id):
    with db.transaction() as conn:
        if not conn.execute('DELETE FROM labels WHERE id = ? AND family_id = ?', (label_id, g.family_id)).rowcount:
            abort(404, 'Label not found')
    return jsonify(ok=True)
