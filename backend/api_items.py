"""API: items (to-dos, deadlines, appointments), their questions/checklist and attachments."""
import calendar
import datetime
import os
import re
import secrets

from flask import Blueprint, abort, g, jsonify, request, send_file

import db
import i18n
import notify
import shopping
import webhooks
from common import body, family_member, family_person, placeholders, text, valid_date, valid_time

bp = Blueprint('items', __name__)

MAX_CHECKS = 100
MAX_ATTACHMENTS = 50
MAX_LABELS = 20
MAX_COMMENT = 5000
# Accepted files: extension -> media type. Only images and PDFs are shown in the browser,
# everything else is always downloaded.
FILE_TYPES = {
    'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp',
    'gif': 'image/gif', 'heic': 'image/heic', 'heif': 'image/heif', 'txt': 'text/plain',
    'doc': 'application/msword', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'odt': 'application/vnd.oasis.opendocument.text', 'xls': 'application/vnd.ms-excel',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'csv': 'text/csv',
    'zip': 'application/zip', 'dcm': 'application/dicom',
}
INLINE = {'application/pdf', 'image/jpeg', 'image/png', 'image/webp', 'image/gif'}


def files_dir():
    # Read at call time: the tests point db.DATA_DIR at a temporary directory
    return os.path.join(db.DATA_DIR, 'files')


# ---------- Dates ----------

def add_interval(date_str, unit, every):
    """Next occurrence; months are clamped to the last day (31 Jan + 1 month = 28/29 Feb)."""
    d = datetime.date.fromisoformat(date_str)
    if unit == 'day':
        return (d + datetime.timedelta(days=every)).isoformat()
    if unit == 'week':
        return (d + datetime.timedelta(weeks=every)).isoformat()
    months = every * (12 if unit == 'year' else 1)
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    return datetime.date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1])).isoformat()


# ---------- Reading ----------

def _load(conn, where, params, order='i.due_date IS NULL, i.due_date, i.due_time IS NULL, i.due_time, i.id', limit=None, dav=False,
          trash=False):
    """Items of the current family matching `where`; those in the trash only with trash=True."""
    deleted = 'i.deleted_at IS NOT NULL' if trash else 'i.deleted_at IS NULL'
    items = [dict(r) for r in conn.execute(
        f'''SELECT i.* FROM items i WHERE i.family_id = ? AND {deleted} AND {where} ORDER BY {order}{f" LIMIT {int(limit)}" if limit else ""}''',
        (g.family_id, *params))]
    if not items:
        return []
    ids = [i['id'] for i in items]
    checks, files, labels, comments = {}, {}, {}, {}
    for r in conn.execute(f'SELECT id, item_id, text, answer, done FROM item_checks WHERE item_id IN ({placeholders(ids)}) '
                          'ORDER BY position, id', ids):
        checks.setdefault(r['item_id'], []).append({'id': r['id'], 'text': r['text'], 'answer': r['answer'], 'done': bool(r['done'])})
    for r in conn.execute(f'SELECT id, item_id, name, mime, size, created_at FROM attachments WHERE item_id IN ({placeholders(ids)}) '
                          'ORDER BY id', ids):
        files.setdefault(r['item_id'], []).append({k: r[k] for k in ('id', 'name', 'mime', 'size', 'created_at')})
    for r in conn.execute(f'''SELECT il.item_id, il.label_id FROM item_labels il JOIN labels l ON l.id = il.label_id
                              WHERE il.item_id IN ({placeholders(ids)}) ORDER BY l.name COLLATE NOCASE''', ids):
        labels.setdefault(r['item_id'], []).append(r['label_id'])
    for r in conn.execute(f'SELECT item_id, COUNT(*) n FROM comments WHERE item_id IN ({placeholders(ids)}) GROUP BY item_id', ids):
        comments[r['item_id']] = r['n']
    for i in items:
        i['checks'] = checks.get(i['id'], [])
        i['attachments'] = files.get(i['id'], [])
        i['labels'] = labels.get(i['id'], [])
        i['comment_count'] = comments.get(i['id'], 0)
        i['done'] = bool(i['done_at'])
        for k in ('family_id',) if dav else ('family_id', 'caldav_uid', 'caldav_name'):
            del i[k]
    return items


def _one(conn, item_id):
    found = _load(conn, 'i.id = ?', (item_id,))
    if not found:
        abort(404, 'Item not found')
    return found[0]


@bp.get('/items')
def list_items():
    """Open items, plus those done in the last `done_days` days (default 7).
    ?done=1 instead lists done items, most recent first (archive)."""
    with db.transaction() as conn:
        if request.args.get('done') == '1':
            items = _load(conn, 'i.done_at IS NOT NULL', (), order='i.done_at DESC', limit=300)
        else:
            try:
                days = max(0, min(int(request.args.get('done_days', 7)), 365))
            except ValueError:
                days = 7
            items = _load(conn, "(i.done_at IS NULL OR i.done_at > datetime('now', ?))", (f'-{days} days',))
    return jsonify(items)


@bp.get('/items/<int:item_id>')
def get_item(item_id):
    """One item, with its comments and history (who created, changed, completed it)."""
    with db.transaction() as conn:
        item = _one(conn, item_id)
        item['comments'] = [dict(r) for r in conn.execute(
            'SELECT id, user_id, text, created_at FROM comments WHERE item_id = ? ORDER BY id', (item_id,))]
        item['history'] = [dict(r) for r in conn.execute(
            'SELECT user_id, action, created_at FROM item_events WHERE item_id = ? ORDER BY id DESC LIMIT 50', (item_id,))]
        return jsonify(item)


# ---------- Writing ----------

def _fields(conn, d):
    kind = d.get('kind', 'task')
    if kind not in db.KINDS:
        abort(400, 'Invalid type')
    title = text(d.get('title'), 200)
    if not title:
        abort(400, 'Title is required')
    category = d.get('category') or 'other'
    if category not in db.CATEGORIES:
        abort(400, 'Invalid category')
    due_date = valid_date(d['due_date']) if d.get('due_date') else None
    if kind in ('note', 'birthday') and not due_date:
        abort(400, 'A date is required')
    # Notes and birthdays are whole days; birthdays repeat by themselves every year
    timed = kind not in ('note', 'birthday')
    due_time = valid_time(d.get('due_time')) if due_date and timed else None
    end_time = valid_time(d.get('end_time'), 'end time') if due_time else None
    end_date = None
    if kind == 'note' and d.get('end_date'):
        end_date = valid_date(d['end_date'], 'end date')
        if end_date < due_date:
            abort(400, 'The period ends before it starts')
        if end_date == due_date:
            end_date = None
    try:
        priority = int(d.get('priority') or 0)
    except (TypeError, ValueError):
        abort(400, 'Invalid priority')
    if priority not in db.PRIORITIES:
        abort(400, 'Invalid priority')
    # In charge: a member with an account or a person without one (never both)
    person_id = family_person(conn, d.get('person_id'))
    assignee_id = None if person_id else family_member(conn, d.get('assignee_id'))
    recur_unit = (d.get('recur_unit') or None) if timed else None
    recur_every = None
    if recur_unit:
        if recur_unit not in db.RECUR_UNITS:
            abort(400, 'Invalid repetition')
        try:
            recur_every = int(d.get('recur_every') or 1)
        except (TypeError, ValueError):
            abort(400, 'Invalid repetition')
        if not 1 <= recur_every <= 100:
            abort(400, 'Invalid repetition')
        if not due_date:
            abort(400, 'A repeating item needs a date')
    recur_from = d.get('recur_from') or 'due'
    if recur_from not in db.RECUR_FROM:
        abort(400, 'Invalid repetition')
    if not recur_unit:
        recur_from = 'due'
    list_id = family_list(conn, d.get('list_id'))
    remind_days = d.get('remind_days')
    if remind_days in (None, ''):
        remind_days = None
    else:
        try:
            remind_days = int(remind_days)
        except (TypeError, ValueError):
            abort(400, 'Invalid reminder')
        if not 0 <= remind_days <= 365:
            abort(400, 'Invalid reminder')
    remind_time = valid_time(d.get('remind_time'), 'reminder time') if remind_days is not None and due_date else None
    section = d.get('section') or None
    if section is not None and section not in db.SECTIONS:
        abort(400, 'Invalid aisle')
    rotation = _rotation(conn, d.get('rotation')) if recur_unit else None
    if rotation:
        turns = rotation.split(',')
        current = f'u{assignee_id}' if assignee_id else f'p{person_id}' if person_id else None
        if current not in turns:  # whose turn it is must be one of those in turn
            current = turns[0]
            assignee_id, person_id = (int(current[1:]), None) if current[0] == 'u' else (None, int(current[1:]))
    return {
        'kind': kind, 'title': title, 'notes': text(d.get('notes'), 10000), 'category': category,
        'subject': text(d.get('subject'), 80), 'due_date': due_date, 'due_time': due_time, 'end_time': end_time,
        'location': text(d.get('location'), 200) if timed else '', 'assignee_id': assignee_id, 'person_id': person_id,
        'recur_unit': recur_unit, 'recur_every': recur_every, 'remind_days': remind_days,
        'priority': priority, 'end_date': end_date, 'list_id': list_id, 'recur_from': recur_from, 'remind_time': remind_time,
        'quantity': text(d.get('quantity'), 40), 'section': section, 'rotation': rotation,
    }


def _rotation(conn, value):
    """Who takes turns: list like ['u1', 'p3', 'u2'] (members u<id>, people p<id>) → 'u1,p3,u2', or None."""
    if value in (None, '', []):
        return None
    if isinstance(value, str):
        value = value.split(',')
    if not isinstance(value, list) or len(value) > 20:
        abort(400, 'Invalid turns')
    out = []
    for v in value:
        v = str(v).strip()
        if not re.fullmatch(r'[up]\d+', v) or v in out:
            abort(400, 'Invalid turns')
        (family_member if v[0] == 'u' else family_person)(conn, int(v[1:]))
        out.append(v)
    return ','.join(out) if len(out) > 1 else None


def family_list(conn, value):
    """Id of a list of the current family, None when empty, otherwise 400."""
    if value in (None, '', 0):
        return None
    try:
        lid = int(value)
    except (TypeError, ValueError):
        abort(400, 'List not found')
    if not conn.execute('SELECT 1 FROM lists WHERE family_id = ? AND id = ?', (g.family_id, lid)).fetchone():
        abort(400, 'List not found')
    return lid


def label_ids(conn, labels):
    """Label ids from a list of ids or names; names that don't exist yet become new labels."""
    if not isinstance(labels, list) or len(labels) > MAX_LABELS:
        abort(400, 'Invalid labels')
    out = []
    for v in labels:
        if isinstance(v, int) and not isinstance(v, bool):
            row = conn.execute('SELECT id FROM labels WHERE id = ? AND family_id = ?', (v, g.family_id)).fetchone()
            if not row:
                abort(400, 'Invalid labels')
            lid = row[0]
        elif isinstance(v, str) and text(v, 40).lstrip('#*'):
            name = text(v, 40).lstrip('#*')
            row = conn.execute('SELECT id FROM labels WHERE family_id = ? AND name = ? COLLATE NOCASE', (g.family_id, name)).fetchone()
            lid = row[0] if row else conn.execute('INSERT INTO labels (family_id, name, color) VALUES (?,?,?)',
                                                  (g.family_id, name, next_color(conn))).lastrowid
        else:
            abort(400, 'Invalid labels')
        if lid not in out:
            out.append(lid)
    return out


def next_color(conn):
    """A colour for a new label: the least used one."""
    used = {r[0]: r[1] for r in conn.execute('SELECT color, COUNT(*) FROM labels WHERE family_id = ? GROUP BY color', (g.family_id,))}
    return min(db.COLORS[:-1], key=lambda c: used.get(c, 0))


def _save_labels(conn, item_id, labels):
    if labels is None:
        return
    ids = label_ids(conn, labels)
    conn.execute('DELETE FROM item_labels WHERE item_id = ?', (item_id,))
    for lid in ids:
        conn.execute('INSERT INTO item_labels (item_id, label_id) VALUES (?,?)', (item_id, lid))


def log(conn, item_id, action, user_id=None):
    conn.execute('INSERT INTO item_events (item_id, user_id, action) VALUES (?,?,?)',
                 (item_id, user_id if user_id is not None else g.user['id'], action))


def _notify_assigned(conn, item, before_assignee=None):
    """Tell a member something was put in their hands by someone else."""
    uid = item['assignee_id']
    if not uid or uid == g.user['id'] or uid == before_assignee:
        return
    lang = notify.language_of(conn, uid)
    notify.notify(conn, uid, g.family_id, 'assigned', i18n.tr('{name} assigned you: {title}', lang, name=g.user['name'], title=item['title']),
                  notify.when_text(item, lang), item_id=item['id'], actor_id=g.user['id'])


def _save_checks(conn, item_id, checks):
    if checks is None:
        return
    if not isinstance(checks, list) or len(checks) > MAX_CHECKS:
        abort(400, 'Invalid questions')
    conn.execute('DELETE FROM item_checks WHERE item_id = ?', (item_id,))
    for pos, c in enumerate(checks):
        if not isinstance(c, dict):
            abort(400, 'Invalid questions')
        t = text(c.get('text'), 1000)
        if not t:
            continue
        conn.execute('INSERT INTO item_checks (item_id, position, text, answer, done) VALUES (?,?,?,?,?)',
                     (item_id, pos, t, text(c.get('answer'), 10000), 1 if c.get('done') else 0))


@bp.post('/items')
def create_item():
    d = body()
    with db.transaction() as conn:
        item = insert_item(conn, d)
        return jsonify(item), 201


def insert_item(conn, d):
    """Create an item from API data (validated); in a list it goes last, with its aisle and in the list's history."""
    f = _fields(conn, d)
    lst = conn.execute('SELECT * FROM lists WHERE id = ?', (f['list_id'],)).fetchone() if f['list_id'] else None
    if lst:
        f['position'] = conn.execute('SELECT COALESCE(MAX(position), 0) + 1 FROM items WHERE list_id = ?', (lst['id'],)).fetchone()[0]
        if lst['kind'] == 'checklist':
            if not f['section']:
                f['section'] = shopping.section_for(conn, lst['id'], f['title'])
            shopping.remember(conn, lst['id'], f['title'], f['section'] if d.get('section') else None)
    cols = list(f)
    item_id = conn.execute(f'INSERT INTO items (family_id, created_by, {", ".join(cols)}) '
                           f'VALUES (?, ?, {placeholders(cols)})', (g.family_id, g.user['id'], *f.values())).lastrowid
    _save_checks(conn, item_id, d.get('checks'))
    _save_labels(conn, item_id, d.get('labels'))
    log(conn, item_id, 'created')
    item = _one(conn, item_id)
    _notify_assigned(conn, item)
    webhooks.emit(conn, g.family_id, 'item.created', item, g.user['id'])
    return item


@bp.put('/items/<int:item_id>')
def update_item(item_id):
    d = body()
    with db.transaction() as conn:
        before = _one(conn, item_id)
        f = _fields(conn, d)
        conn.execute(f'UPDATE items SET {", ".join(c + " = ?" for c in f)}, updated_at = datetime(\'now\') WHERE id = ?',
                     (*f.values(), item_id))
        _save_checks(conn, item_id, d.get('checks'))
        _save_labels(conn, item_id, d.get('labels'))
        item = _one(conn, item_id)
        if _changed(before, item):
            log(conn, item_id, 'updated')
            webhooks.emit(conn, g.family_id, 'item.updated', item, g.user['id'])
        # An aisle chosen by hand is learned for next time
        if item['list_id'] and item['section'] and item['section'] != before['section']:
            shopping.remember(conn, item['list_id'], item['title'], item['section'])
        _notify_assigned(conn, item, before['assignee_id'])
        return jsonify(item)


def _changed(a, b):
    skip = {'updated_at', 'checks', 'attachments', 'comment_count', 'position'}
    return any(a[k] != b[k] for k in a if k not in skip) or \
        [(c['text'], c['answer'], c['done']) for c in a['checks']] != [(c['text'], c['answer'], c['done']) for c in b['checks']]


@bp.patch('/items/<int:item_id>/checks/<int:check_id>')
def toggle_check(item_id, check_id):
    """Tick/untick one checklist entry without resending the whole item."""
    d = body()
    with db.transaction() as conn:
        _one(conn, item_id)
        cur = conn.execute('UPDATE item_checks SET done = ? WHERE id = ? AND item_id = ?',
                           (1 if d.get('done') else 0, check_id, item_id))
        if not cur.rowcount:
            abort(404, 'Item not found')
        conn.execute("UPDATE items SET updated_at = datetime('now') WHERE id = ?", (item_id,))
        return jsonify(_one(conn, item_id))


COPIED = ('kind', 'title', 'notes', 'category', 'subject', 'due_time', 'end_time', 'location', 'assignee_id', 'person_id',
          'recur_unit', 'recur_every', 'recur_from', 'remind_days', 'remind_time', 'priority', 'list_id', 'quantity', 'section',
          'rotation', 'position')


def next_turn(item):
    """(assignee_id, person_id) of whoever is next in turn after the current one."""
    turns = item['rotation'].split(',')
    current = f"u{item['assignee_id']}" if item['assignee_id'] else f"p{item['person_id']}" if item['person_id'] else None
    nxt = turns[(turns.index(current) + 1) % len(turns)] if current in turns else turns[0]
    return (int(nxt[1:]), None) if nxt[0] == 'u' else (None, int(nxt[1:]))


def complete_item(conn, item, user_id, family_id, today=None):
    """Mark an item done; a repeating one gets its next occurrence, whose id is returned.
    The next date counts from the due date, or from today when the item repeats "from completion"."""
    conn.execute("UPDATE items SET done_at = datetime('now'), done_by = ?, updated_at = datetime('now') WHERE id = ?",
                 (user_id, item['id']))
    log(conn, item['id'], 'done', user_id)
    new_id = None
    if item['recur_unit'] and item['due_date']:
        copy = {k: item[k] for k in COPIED}
        base = (today or datetime.date.today()).isoformat() if item['recur_from'] == 'done' else item['due_date']
        copy['due_date'] = add_interval(base, item['recur_unit'], item['recur_every'] or 1)
        if item['rotation']:
            copy['assignee_id'], copy['person_id'] = next_turn(item)
        cols = list(copy)
        new_id = conn.execute(f'INSERT INTO items (family_id, created_by, spawned_from, {", ".join(cols)}) '
                              f'VALUES (?, ?, ?, {placeholders(cols)})',
                              (family_id, user_id, item['id'], *copy.values())).lastrowid
        # A checklist (not the questions/answers of a visit) carries over, unticked
        if item['kind'] != 'appointment':
            for pos, c in enumerate(item['checks']):
                conn.execute('INSERT INTO item_checks (item_id, position, text) VALUES (?,?,?)', (new_id, pos, c['text']))
        for lid in item['labels']:
            conn.execute('INSERT INTO item_labels (item_id, label_id) VALUES (?,?)', (new_id, lid))
        # Same timestamps: "untouched", so undo can remove it
        conn.execute('UPDATE items SET updated_at = created_at WHERE id = ?', (new_id,))
        # The next one in turn is told it is up to them
        if copy['assignee_id'] and copy['assignee_id'] != user_id and item['rotation']:
            lang = notify.language_of(conn, copy['assignee_id'])
            notify.notify(conn, copy['assignee_id'], family_id, 'assigned', i18n.tr('Your turn: {title}', lang, title=item['title']),
                          notify.when_text({**copy, 'due_date': copy['due_date']}, lang), item_id=new_id, actor_id=user_id)
    # Someone else did what was assigned to you
    if item['assignee_id'] and item['assignee_id'] != user_id:
        actor = conn.execute('SELECT name FROM users WHERE id = ?', (user_id,)).fetchone()
        lang = notify.language_of(conn, item['assignee_id'])
        notify.notify(conn, item['assignee_id'], family_id, 'done',
                      i18n.tr('{name} completed: {title}', lang, name=actor['name'] if actor else '?', title=item['title']),
                      item_id=item['id'], actor_id=user_id)
    return new_id


@bp.post('/items/<int:item_id>/done')
def complete(item_id):
    """Mark as done. A repeating item gets its next occurrence (returned as `next`)."""
    with db.transaction() as conn:
        item = _one(conn, item_id)
        if item['done']:
            return jsonify(item=item, next=None)
        new_id = complete_item(conn, item, g.user['id'], g.family_id)
        done = _one(conn, item_id)
        webhooks.emit(conn, g.family_id, 'item.done', done, g.user['id'])
        return jsonify(item=done, next=_one(conn, new_id) if new_id else None)


@bp.post('/items/<int:item_id>/undo')
def undo(item_id):
    """Back to open. The next occurrence created on completion is removed if nobody touched it."""
    with db.transaction() as conn:
        _one(conn, item_id)
        reopen_item(conn, item_id, g.family_id)
        log(conn, item_id, 'reopened')
        item = _one(conn, item_id)
        webhooks.emit(conn, g.family_id, 'item.reopened', item, g.user['id'])
        return jsonify(item)


def reopen_item(conn, item_id, family_id):
    """Back to open; the next occurrence created on completion goes away if nobody touched it."""
    conn.execute("UPDATE items SET done_at = NULL, done_by = NULL, updated_at = datetime('now') WHERE id = ?", (item_id,))
    for r in conn.execute('''SELECT id FROM items WHERE spawned_from = ? AND family_id = ? AND done_at IS NULL AND deleted_at IS NULL
                             AND updated_at = created_at
                             AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.item_id = items.id)
                             AND NOT EXISTS (SELECT 1 FROM comments c WHERE c.item_id = items.id)''',
                          (item_id, family_id)).fetchall():
        conn.execute('DELETE FROM items WHERE id = ?', (r['id'],))


@bp.delete('/items/<int:item_id>')
def delete_item(item_id):
    """To the trash: it can be restored for TRASH_DAYS days."""
    with db.transaction() as conn:
        item = _one(conn, item_id)
        trash_item(conn, item_id)
        webhooks.emit(conn, g.family_id, 'item.deleted', item, g.user['id'])
    return jsonify(ok=True)


def trash_item(conn, item_id):
    # The CalDAV name is freed: a phone may create a new item with it
    conn.execute("UPDATE items SET deleted_at = datetime('now'), caldav_name = NULL, updated_at = datetime('now') WHERE id = ?",
                 (item_id,))
    log(conn, item_id, 'deleted')


@bp.get('/trash')
def trash():
    with db.transaction() as conn:
        return jsonify(_load(conn, '1', (), order='i.deleted_at DESC', limit=300, trash=True))


@bp.post('/items/<int:item_id>/restore')
def restore(item_id):
    with db.transaction() as conn:
        if not _load(conn, 'i.id = ?', (item_id,), trash=True):
            abort(404, 'Item not found')
        conn.execute("UPDATE items SET deleted_at = NULL, updated_at = datetime('now') WHERE id = ?", (item_id,))
        log(conn, item_id, 'restored')
        return jsonify(_one(conn, item_id))


@bp.delete('/trash')
def empty_trash():
    with db.transaction() as conn:
        stored = delete_items(conn, 'family_id = ? AND deleted_at IS NOT NULL', (g.family_id,))
    remove_files(stored)
    return jsonify(ok=True)


def purge_trash():
    """Delete for good what has been in the trash longer than TRASH_DAYS (all families)."""
    with db.transaction() as conn:
        stored = delete_items(conn, "deleted_at IS NOT NULL AND deleted_at < datetime('now', ?)", (f'-{db.TRASH_DAYS} days',))
    remove_files(stored)
    return len(stored)


# ---------- Quick actions ----------

@bp.post('/items/<int:item_id>/postpone')
def postpone(item_id):
    """Move to another day (a notice covering a period moves as a whole)."""
    to = valid_date(body().get('date'))
    with db.transaction() as conn:
        item = _one(conn, item_id)
        if item['kind'] == 'birthday':
            abort(400, 'Birthdays cannot be moved')
        end = item['end_date']
        if end and item['due_date']:
            delta = datetime.date.fromisoformat(to) - datetime.date.fromisoformat(item['due_date'])
            end = (datetime.date.fromisoformat(end) + delta).isoformat()
        conn.execute("UPDATE items SET due_date = ?, end_date = ?, updated_at = datetime('now') WHERE id = ?", (to, end, item_id))
        log(conn, item_id, 'postponed')
        item = _one(conn, item_id)
        webhooks.emit(conn, g.family_id, 'item.updated', item, g.user['id'])
        return jsonify(item)


def delete_items(conn, where, params):
    """Delete the matching items; returns their stored file names (to remove once committed)."""
    stored = [r[0] for r in conn.execute(f'SELECT stored_name FROM attachments WHERE item_id IN (SELECT id FROM items WHERE {where})',
                                         params)]
    conn.execute(f'DELETE FROM items WHERE {where}', params)
    return stored


def remove_files(stored):
    for s in stored:
        _remove_file(s)


# ---------- Comments ----------

@bp.post('/items/<int:item_id>/comments')
def add_comment(item_id):
    t = text(body().get('text'), MAX_COMMENT)
    if not t:
        abort(400, 'Write something first')
    with db.transaction() as conn:
        item = _one(conn, item_id)
        cid = conn.execute('INSERT INTO comments (item_id, user_id, text) VALUES (?,?,?)', (item_id, g.user['id'], t)).lastrowid
        # Whoever the item concerns (assignee, creator, earlier commenters), except the author
        who = {item['assignee_id'], item['created_by']}
        who |= {r[0] for r in conn.execute('SELECT DISTINCT user_id FROM comments WHERE item_id = ?', (item_id,))}
        members = set(notify.family_users(conn, g.family_id))
        for uid in (who & members) - {g.user['id']}:
            lang = notify.language_of(conn, uid)
            notify.notify(conn, uid, g.family_id, 'comment',
                          i18n.tr('{name} commented on: {title}', lang, name=g.user['name'], title=item['title']), t[:300],
                          item_id=item_id, actor_id=g.user['id'])
        comment = dict(conn.execute('SELECT id, user_id, text, created_at FROM comments WHERE id = ?', (cid,)).fetchone())
        webhooks.emit(conn, g.family_id, 'comment.created', {**comment, 'item_id': item_id, 'item_title': item['title']}, g.user['id'])
        return jsonify(comment), 201


@bp.delete('/comments/<int:comment_id>')
def delete_comment(comment_id):
    """Only the author removes a comment."""
    with db.transaction() as conn:
        c = conn.execute('''SELECT c.* FROM comments c JOIN items i ON i.id = c.item_id
                            WHERE c.id = ? AND i.family_id = ?''', (comment_id, g.family_id)).fetchone()
        if not c:
            abort(404, 'Comment not found')
        if c['user_id'] != g.user['id']:
            abort(403, 'You can only delete your own comments')
        conn.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
    return jsonify(ok=True)


# ---------- Attachments ----------

def _remove_file(stored_name):
    try:
        os.remove(os.path.join(files_dir(), stored_name))
    except FileNotFoundError:
        pass


@bp.post('/items/<int:item_id>/attachments')
def upload(item_id):
    f = request.files.get('file')
    if not f or not f.filename:
        abort(400, 'No file uploaded')
    name = os.path.basename(f.filename.replace('\\', '/'))[:200] or 'file'
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in FILE_TYPES:
        abort(400, 'File type not allowed')
    with db.transaction() as conn:
        _one(conn, item_id)
        if conn.execute('SELECT COUNT(*) FROM attachments WHERE item_id = ?', (item_id,)).fetchone()[0] >= MAX_ATTACHMENTS:
            abort(400, 'Too many attachments')
        os.makedirs(files_dir(), exist_ok=True)
        stored = secrets.token_hex(16) + '.' + ext
        path = os.path.join(files_dir(), stored)
        f.save(path)
        size = os.path.getsize(path)
        try:
            conn.execute('INSERT INTO attachments (item_id, name, mime, size, stored_name, uploaded_by) VALUES (?,?,?,?,?,?)',
                         (item_id, name, FILE_TYPES[ext], size, stored, g.user['id']))
        except Exception:
            _remove_file(stored)
            raise
        return jsonify(_one(conn, item_id)), 201


def _attachment(conn, attachment_id):
    a = conn.execute('''SELECT a.* FROM attachments a JOIN items i ON i.id = a.item_id
                        WHERE a.id = ? AND i.family_id = ?''', (attachment_id, g.family_id)).fetchone()
    if not a:
        abort(404, 'File not found')
    return a


@bp.get('/attachments/<int:attachment_id>')
def download(attachment_id):
    with db.transaction() as conn:
        a = _attachment(conn, attachment_id)
    path = os.path.join(files_dir(), a['stored_name'])
    if not os.path.isfile(path):
        abort(404, 'File not found')
    inline = a['mime'] in INLINE and request.args.get('download') != '1'
    resp = send_file(path, mimetype=a['mime'], as_attachment=not inline, download_name=a['name'], max_age=0)
    # No scripts ever run from an uploaded file (the media type comes from our whitelist, never from the upload)
    resp.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; object-src 'self'"
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


@bp.delete('/attachments/<int:attachment_id>')
def delete_attachment(attachment_id):
    with db.transaction() as conn:
        a = _attachment(conn, attachment_id)
        conn.execute('DELETE FROM attachments WHERE id = ?', (attachment_id,))
        item = _one(conn, a['item_id'])
    _remove_file(a['stored_name'])
    return jsonify(item)


def cleanup_orphan_files():
    """Delete stored files whose row is gone (e.g. a family deleted with its account)."""
    d = files_dir()
    if not os.path.isdir(d):
        return 0
    with db.transaction() as conn:
        known = {r[0] for r in conn.execute('SELECT stored_name FROM attachments')}
    removed = 0
    for name in os.listdir(d):
        if name not in known:
            os.remove(os.path.join(d, name))
            removed += 1
    return removed
