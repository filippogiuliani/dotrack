"""Items: validation, questions/checklist, completion of repeating items, attachments."""
import io
import os

import api_items
import db
from conftest import ok


def test_create_update_and_validation(family):
    f = family
    c = f.c
    assert c.post('/api/items', json={'title': ''}).status_code == 400
    assert c.post('/api/items', json={'title': 'x', 'kind': 'nope'}).status_code == 400
    assert c.post('/api/items', json={'title': 'x', 'category': 'nope'}).status_code == 400
    assert c.post('/api/items', json={'title': 'x', 'due_date': '2026-11-10', 'due_time': '25:00'}).status_code == 400
    assert c.post('/api/items', json={'title': 'x', 'recur_unit': 'year'}).status_code == 400  # needs a date
    assert c.post('/api/items', json={'title': 'x', 'remind_days': -1}).status_code == 400

    item = f.item(kind='appointment', title='Pediatra', category='health', subject='Giulia', due_date='2026-11-20',
                  due_time='10:30', end_time='11:00', location='Studio Rossi', remind_days=1,
                  checks=[{'text': 'Vaccino?'}, {'text': ''}, {'text': 'Peso?', 'answer': '8 kg'}])
    assert (item['kind'], item['due_time'], item['end_time'], item['remind_days']) == ('appointment', '10:30', '11:00', 1)
    assert [(q['text'], q['answer']) for q in item['checks']] == [('Vaccino?', ''), ('Peso?', '8 kg')]

    # Answers filled in during the visit
    item['checks'][0]['answer'] = 'Sì, a gennaio'
    item = ok(c.put(f"/api/items/{item['id']}", json=item))
    assert item['checks'][0]['answer'] == 'Sì, a gennaio'
    # Without a date the time is dropped
    item = ok(c.put(f"/api/items/{item['id']}", json={**item, 'due_date': None}))
    assert item['due_time'] is None and item['due_date'] is None

    ok(c.delete(f"/api/items/{item['id']}"))
    assert c.get(f"/api/items/{item['id']}").status_code == 404


def test_checklist_toggle(family):
    item = family.item(checks=[{'text': 'A'}, {'text': 'B'}])
    check = item['checks'][1]['id']
    item = ok(family.c.patch(f"/api/items/{item['id']}/checks/{check}", json={'done': True}))
    assert [q['done'] for q in item['checks']] == [False, True]


def test_add_interval_clamps_months():
    assert api_items.add_interval('2026-01-31', 'month', 1) == '2026-02-28'
    assert api_items.add_interval('2028-02-29', 'year', 1) == '2029-02-28'
    assert api_items.add_interval('2026-11-09', 'year', 10) == '2036-11-09'
    assert api_items.add_interval('2026-11-09', 'week', 2) == '2026-11-23'
    assert api_items.add_interval('2026-12-15', 'month', 3) == '2027-03-15'


def test_completing_a_repeating_deadline_creates_the_next(family):
    f = family
    f.add_partner()
    item = f.item(kind='deadline', title='Bollo auto', category='car', subject='Panda', due_date='2026-11-30',
                  recur_unit='year', recur_every=1, remind_days=30, assignee_id=f.puid, checks=[{'text': 'Pagare online'}])
    r = ok(f.p.post(f"/api/items/{item['id']}/done"))
    assert r['item']['done'] and r['item']['done_by'] == f.puid
    nxt = r['next']
    assert (nxt['title'], nxt['due_date'], nxt['assignee_id'], nxt['remind_days']) == ('Bollo auto', '2027-11-30', f.puid, 30)
    assert [q['text'] for q in nxt['checks']] == ['Pagare online'] and not nxt['done']
    # Completing twice does nothing more
    assert ok(f.c.post(f"/api/items/{item['id']}/done"))['next'] is None
    # Undo removes the untouched next occurrence
    ok(f.c.post(f"/api/items/{item['id']}/undo"))
    titles = [(i['due_date'], i['done']) for i in ok(f.c.get('/api/items'))]
    assert titles == [('2026-11-30', False)]


def test_undo_keeps_a_next_occurrence_that_was_edited(family):
    f = family
    item = f.item(title='Revisione', due_date='2026-11-30', recur_unit='year', recur_every=2)
    nxt = ok(f.c.post(f"/api/items/{item['id']}/done"))['next']
    with db.transaction() as conn:  # simulate an edit made later
        conn.execute("UPDATE items SET updated_at = datetime('now', '+1 minute') WHERE id = ?", (nxt['id'],))
    ok(f.c.post(f"/api/items/{item['id']}/undo"))
    assert {i['id'] for i in ok(f.c.get('/api/items'))} == {item['id'], nxt['id']}


def test_done_items_list(family):
    f = family
    a = f.item(title='A')
    f.item(title='B')
    ok(f.c.post(f"/api/items/{a['id']}/done"))
    assert {i['title'] for i in ok(f.c.get('/api/items'))} == {'A', 'B'}       # done recently: still listed
    assert {i['title'] for i in ok(f.c.get('/api/items?done_days=0'))} == {'B'}
    assert [i['title'] for i in ok(f.c.get('/api/items?done=1'))] == ['A']


def test_attachments(family):
    f = family
    item = f.item(kind='appointment', title='Visita')
    up = lambda name, data=b'%PDF-1.4 test': f.c.post(f"/api/items/{item['id']}/attachments",
                                                        data={'file': (io.BytesIO(data), name)}, content_type='multipart/form-data')
    assert up('evil.html').status_code == 400
    assert up('noext').status_code == 400
    item = ok(up('Referto 1.pdf'), 201)
    att = item['attachments'][0]
    assert (att['name'], att['mime'], att['size']) == ('Referto 1.pdf', 'application/pdf', 13)

    r = f.c.get(f"/api/attachments/{att['id']}")
    assert r.status_code == 200 and r.data == b'%PDF-1.4 test' and r.mimetype == 'application/pdf'
    assert 'inline' in r.headers['Content-Disposition']
    assert r.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'attachment' in f.c.get(f"/api/attachments/{att['id']}?download=1").headers['Content-Disposition']
    item2 = ok(up('notes.docx', b'PK'), 201)
    docx = item2['attachments'][1]['id']
    assert 'attachment' in f.c.get(f'/api/attachments/{docx}').headers['Content-Disposition']

    stored = os.listdir(api_items.files_dir())
    assert len(stored) == 2
    ok(f.c.delete(f"/api/attachments/{att['id']}"))
    assert len(os.listdir(api_items.files_dir())) == 1
    # Deleting the item puts it in the trash, files included; emptying the trash deletes them
    ok(f.c.delete(f"/api/items/{item['id']}"))
    assert len(os.listdir(api_items.files_dir())) == 1
    ok(f.c.delete('/api/trash'))
    assert os.listdir(api_items.files_dir()) == []


def test_orphan_files_are_cleaned_up(family):
    f = family
    item = f.item()
    ok(f.c.post(f"/api/items/{item['id']}/attachments", data={'file': (io.BytesIO(b'x'), 'a.png')},
                content_type='multipart/form-data'), 201)
    open(os.path.join(api_items.files_dir(), 'stray.pdf'), 'wb').close()
    assert api_items.cleanup_orphan_files() == 1
    assert len(os.listdir(api_items.files_dir())) == 1
