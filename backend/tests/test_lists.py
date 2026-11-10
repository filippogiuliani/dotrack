"""Lists, projects, labels, repeating from completion, comments and history."""
import datetime
import io

import api_items
import db
from conftest import ok


def test_lists_crud_and_items(family):
    c = family.c
    assert c.post('/api/lists', json={'name': ''}).status_code == 400
    assert c.post('/api/lists', json={'name': 'X', 'kind': 'nope'}).status_code == 400
    assert c.post('/api/lists', json={'name': 'X', 'color': 'nope'}).status_code == 400
    spesa = ok(c.post('/api/lists', json={'name': 'Spesa'}), 201)
    bagno = ok(c.post('/api/lists', json={'name': 'Bagno', 'kind': 'project', 'color': 'green'}), 201)
    assert (spesa['kind'], spesa['color'], spesa['open_count']) == ('checklist', 'blue', 0)

    latte = family.item(title='Latte', list_id=spesa['id'])
    family.item(title='Pane', list_id=spesa['id'])
    family.item(title='Piastrelle', list_id=bagno['id'], due_date='2026-12-01')
    assert latte['list_id'] == spesa['id']
    assert c.post('/api/items', json={'title': 'x', 'list_id': 999}).status_code == 400

    ok(c.post(f"/api/items/{latte['id']}/done"))
    lists = {x['name']: x for x in ok(c.get('/api/lists'))}
    assert (lists['Spesa']['open_count'], lists['Spesa']['done_count']) == (1, 1)

    # Clearing what was bought removes only the ticked entries
    assert ok(c.post(f"/api/lists/{spesa['id']}/clear-done"))['removed'] == 1
    assert [i['title'] for i in ok(c.get('/api/items')) if i['list_id'] == spesa['id']] == ['Pane']

    # Rename, archive, reorder
    renamed = ok(c.put(f"/api/lists/{spesa['id']}", json={'name': 'Supermercato', 'archived': True}))
    assert renamed['name'] == 'Supermercato' and renamed['archived'] and renamed['kind'] == 'checklist'
    assert [x['id'] for x in ok(c.put('/api/lists/order', json={'ids': [bagno['id'], spesa['id']]}))][0] == bagno['id']

    # Deleting a list deletes its items
    ok(c.delete(f"/api/lists/{bagno['id']}"))
    assert all(i['title'] != 'Piastrelle' for i in ok(c.get('/api/items')))


def test_lists_are_per_family(family, client):
    from conftest import sign_up
    spesa = ok(family.c.post('/api/lists', json={'name': 'Spesa'}), 201)
    other = client()
    sign_up(other, email='other@example.com', name='Other')
    assert other.put(f"/api/lists/{spesa['id']}", json={'name': 'x'}).status_code == 404
    assert other.post('/api/items', json={'title': 'x', 'list_id': spesa['id']}).status_code == 400
    assert other.delete(f"/api/lists/{spesa['id']}").status_code == 404


def test_deleting_a_list_removes_attachment_files(family):
    c = family.c
    lst = ok(c.post('/api/lists', json={'name': 'Casa'}), 201)
    item = family.item(title='Garanzia', list_id=lst['id'])
    ok(c.post(f"/api/items/{item['id']}/attachments", data={'file': (io.BytesIO(b'%PDF'), 'g.pdf')},
              content_type='multipart/form-data'), 201)
    import os
    assert len(os.listdir(api_items.files_dir())) == 1
    ok(c.delete(f"/api/lists/{lst['id']}"))
    assert os.listdir(api_items.files_dir()) == []


def test_labels(family):
    c = family.c
    casa = ok(c.post('/api/labels', json={'name': '#casa'}), 201)
    assert casa['name'] == 'casa' and casa['color'] in db.COLORS
    assert c.post('/api/labels', json={'name': 'Casa'}).status_code == 409
    # By id or by name; unknown names become new labels
    item = family.item(title='Idraulico', labels=[casa['id'], 'urgente', 'CASA'])
    labels = {x['name']: x for x in ok(c.get('/api/labels'))}
    assert set(labels) == {'casa', 'urgente'}
    assert sorted(item['labels']) == sorted([casa['id'], labels['urgente']['id']])
    assert labels['casa']['count'] == 1
    assert c.post('/api/items', json={'title': 'x', 'labels': [9999]}).status_code == 400
    assert c.post('/api/items', json={'title': 'x', 'labels': 'casa'}).status_code == 400

    # Without `labels` an update keeps them; with [] it removes them
    item = ok(c.put(f"/api/items/{item['id']}", json={**item, 'labels': None}))
    assert len(item['labels']) == 2
    item = ok(c.put(f"/api/items/{item['id']}", json={**item, 'labels': [casa['id']]}))
    assert item['labels'] == [casa['id']]

    renamed = ok(c.put(f"/api/labels/{casa['id']}", json={'name': 'Casa al mare', 'color': 'teal'}))
    assert (renamed['name'], renamed['color']) == ('Casa al mare', 'teal')
    ok(c.delete(f"/api/labels/{casa['id']}"))
    assert ok(c.get(f"/api/items/{item['id']}"))['labels'] == []


def test_repeat_from_completion(family, monkeypatch):
    c = family.c
    today = datetime.date.today()
    item = family.item(title='Filtro cappa', due_date='2020-01-15', recur_unit='month', recur_every=3, recur_from='done',
                       labels=['casa'])
    assert item['recur_from'] == 'done'
    nxt = ok(c.post(f"/api/items/{item['id']}/done"))['next']
    assert nxt['due_date'] == api_items.add_interval(today.isoformat(), 'month', 3)
    assert nxt['recur_from'] == 'done' and nxt['labels'] == item['labels']
    # Undo still removes the untouched next one
    ok(c.post(f"/api/items/{item['id']}/undo"))
    assert c.get(f"/api/items/{nxt['id']}").status_code == 404
    # Without repetition, recur_from goes back to the default
    assert family.item(title='x', recur_from='done')['recur_from'] == 'due'
    assert c.post('/api/items', json={'title': 'x', 'due_date': '2026-01-01', 'recur_unit': 'week', 'recur_from': 'nope'}).status_code == 400


def test_reminder_time(family):
    c = family.c
    item = family.item(title='Pagare', due_date='2026-12-01', remind_days=1, remind_time='18:30')
    assert item['remind_time'] == '18:30'
    assert c.post('/api/items', json={'title': 'x', 'due_date': '2026-12-01', 'remind_days': 1, 'remind_time': '25:00'}).status_code == 400
    # Meaningless without a reminder
    assert family.item(title='y', due_date='2026-12-01', remind_time='18:30')['remind_time'] is None


def test_comments_history_and_notifications(family, pushes):
    f = family
    p = f.add_partner()
    item = f.item(title='Chiamare idraulico', assignee_id=f.puid)
    # Sara is told she was given something to do (by Fil, not by herself)
    notes = ok(p.get('/api/notifications'))
    assert notes['unread'] == 1 and notes['items'][0]['kind'] == 'assigned'
    assert 'Fil' in notes['items'][0]['title'] and 'Chiamare idraulico' in notes['items'][0]['title']
    assert pushes[-1][0] == f.puid and pushes[-1][1]['url'] == f"/#/item/{item['id']}"
    assert ok(f.c.get('/api/notifications'))['unread'] == 0

    # Re-saving with the same assignee says nothing new
    ok(f.c.put(f"/api/items/{item['id']}", json=item))
    assert ok(p.get('/api/notifications'))['unread'] == 1

    assert f.c.post(f"/api/items/{item['id']}/comments", json={'text': ' '}).status_code == 400
    com = ok(f.c.post(f"/api/items/{item['id']}/comments", json={'text': 'Il numero è sul frigo'}), 201)
    assert ok(p.get('/api/notifications'))['items'][0]['kind'] == 'comment'
    ok(p.post(f"/api/items/{item['id']}/comments", json={'text': 'Ok, chiamo domani'}), 201)
    assert ok(f.c.get('/api/notifications'))['items'][0]['body'] == 'Ok, chiamo domani'

    full = ok(f.c.get(f"/api/items/{item['id']}"))
    assert [x['text'] for x in full['comments']] == ['Il numero è sul frigo', 'Ok, chiamo domani']
    assert full['comment_count'] == 2
    # Only the author deletes a comment
    assert p.delete(f"/api/comments/{com['id']}").status_code == 403
    ok(f.c.delete(f"/api/comments/{com['id']}"))

    # Sara does it: history records who did what, Fil is not notified (it wasn't his)
    ok(p.post(f"/api/items/{item['id']}/done"))
    hist = ok(f.c.get(f"/api/items/{item['id']}"))['history']
    assert [(h['action'], h['user_id']) for h in hist][:1] == [('done', f.puid)]
    assert [h['action'] for h in hist][-1] == 'created'

    # Fil completes something assigned to Sara: she is told
    other = f.item(title='Ritirare pacco', assignee_id=f.puid)
    ok(f.c.post(f"/api/items/{other['id']}/done"))
    assert ok(p.get('/api/notifications'))['items'][0]['kind'] == 'done'

    # Mark all as read
    assert ok(p.post('/api/notifications/read', json={}))['unread'] == 0
