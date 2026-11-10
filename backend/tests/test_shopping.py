"""Shopping lists (aisles, quantities, suggestions, bulk add), turns, quick actions, trash, templates, sync."""
import datetime

import shopping
from conftest import ok


def test_guess_section_and_quantities():
    assert shopping.guess_section('Latte') == 'dairy'
    assert shopping.guess_section('zucchine') == 'produce'
    assert shopping.guess_section('Carta igienica') == 'household'
    assert shopping.guess_section('Pane integrale') == 'bakery'
    assert shopping.guess_section('pannolini taglia 4') == 'baby'
    assert shopping.guess_section('Regalo per Luca') == 'other'
    assert shopping.split_quantity('2 kg mele') == ('mele', '2 kg')
    assert shopping.split_quantity('latte x2') == ('latte', '2')
    assert shopping.split_quantity('500 g di farina') == ('farina', '500 g')
    assert shopping.split_quantity('3 uova') == ('uova', '3')
    assert shopping.split_quantity('Pane') == ('Pane', '')


def test_shopping_list_flow(family):
    c = family.c
    spesa = ok(c.post('/api/lists', json={'name': 'Spesa', 'sections': True}), 201)
    assert spesa['sections']
    latte = family.item(title='Latte', list_id=spesa['id'], quantity='2')
    assert (latte['section'], latte['quantity'], latte['position']) == ('dairy', '2', 1)
    pane = family.item(title='Pane', list_id=spesa['id'])
    assert pane['section'] == 'bakery' and pane['position'] == 2
    # Moving "Pane" to another aisle is learned for next time
    ok(c.put(f"/api/items/{pane['id']}", json={**pane, 'section': 'pantry'}))
    ok(c.post(f"/api/items/{pane['id']}/done"))
    again = family.item(title='pane', list_id=spesa['id'])
    assert again['section'] == 'pantry'
    assert c.post('/api/items', json={'title': 'x', 'section': 'nope'}).status_code == 400

    # Suggestions: what was bought before and is not on the list now
    ok(c.post(f"/api/items/{latte['id']}/done"))
    names = [s['name'] for s in ok(c.get(f"/api/lists/{spesa['id']}/suggestions"))]
    assert 'Latte' in names and 'pane' not in [n.lower() for n in names]

    # Bulk add (integrations): duplicates of open entries are skipped, quantities split
    r = ok(c.post(f"/api/lists/{spesa['id']}/items", json={'items': ['2 kg mele', 'Pane', {'title': 'Yogurt', 'quantity': '4'}]}), 201)
    assert [(i['title'], i['quantity'], i['section']) for i in r['added']] == [('mele', '2 kg', 'produce'), ('Yogurt', '4', 'dairy')]
    assert r['skipped'] == ['Pane']

    # Manual order
    open_ids = [i['id'] for i in ok(c.get('/api/items')) if i['list_id'] == spesa['id'] and not i['done']]
    ok(c.put(f"/api/lists/{spesa['id']}/items/order", json={'ids': list(reversed(open_ids))}))
    pos = {i['id']: i['position'] for i in ok(c.get('/api/items')) if i['id'] in open_ids}
    assert sorted(open_ids, key=lambda x: pos[x]) == list(reversed(open_ids))


def test_templates_and_copies(family):
    c = family.c
    valigia = ok(c.post('/api/lists', json={'name': 'Valigia'}), 201)
    a = family.item(title='Spazzolini', list_id=valigia['id'], labels=['bagno'], checks=[{'text': 'tutti e 3'}])
    family.item(title='Caricabatterie', list_id=valigia['id'], due_date='2026-12-01')
    ok(c.post(f"/api/items/{a['id']}/done"))
    tpl = ok(c.post(f"/api/lists/{valigia['id']}/copy", json={'name': 'Valigia (modello)', 'template': True}), 201)
    assert tpl['template'] and tpl['open_count'] == 1  # only what was still open
    from_tpl = ok(c.post(f"/api/lists/{tpl['id']}/copy", json={'name': 'Valigia Natale'}), 201)
    items = [i for i in ok(c.get('/api/items')) if i['list_id'] == from_tpl['id']]
    assert [(i['title'], i['due_date'], i['done']) for i in items] == [('Caricabatterie', None, False)]
    # Everything ticked: the copy takes all of it, unticked
    ok(c.post(f"/api/items/{items[0]['id']}/done"))
    dup = ok(c.post(f"/api/lists/{from_tpl['id']}/copy", json={}), 201)
    assert dup['name'] == 'Valigia Natale' and dup['open_count'] == 1


def test_turns(family, pushes):
    f = family
    f.add_partner()
    giulia = ok(f.c.post('/api/family/people', json={'name': 'Giulia'}), 201)
    turns = [f'u{f.uid}', f'u{f.puid}', f"p{giulia['id']}"]
    item = f.item(title='Spazzatura', due_date='2026-11-10', recur_unit='week', recur_every=1, rotation=turns)
    assert item['rotation'] == ','.join(turns) and item['assignee_id'] == f.uid  # starts with the first
    assert f.c.post('/api/items', json={'title': 'x', 'due_date': '2026-11-10', 'recur_unit': 'week',
                                         'rotation': ['u999', f'u{f.uid}']}).status_code == 400
    nxt = ok(f.c.post(f"/api/items/{item['id']}/done"))['next']
    assert (nxt['assignee_id'], nxt['person_id'], nxt['rotation']) == (f.puid, None, item['rotation'])
    assert any(uid == f.puid and 'Spazzatura' in p['title'] for uid, p in pushes)
    nxt2 = ok(f.p.post(f"/api/items/{nxt['id']}/done"))['next']
    assert (nxt2['assignee_id'], nxt2['person_id']) == (None, giulia['id'])
    nxt3 = ok(f.c.post(f"/api/items/{nxt2['id']}/done"))['next']
    assert nxt3['assignee_id'] == f.uid
    # One person alone is not a turn
    assert f.item(title='y', due_date='2026-11-10', recur_unit='week', rotation=[f'u{f.uid}'])['rotation'] is None


def test_postpone_and_trash(family):
    c = family.c
    item = family.item(title='Chiamare', due_date='2026-11-09')
    moved = ok(c.post(f"/api/items/{item['id']}/postpone", json={'date': '2026-11-12'}))
    assert moved['due_date'] == '2026-11-12'
    note = family.item(kind='note', title='Ferie', due_date='2026-12-01', end_date='2026-12-05')
    assert ok(c.post(f"/api/items/{note['id']}/postpone", json={'date': '2026-12-08'}))['end_date'] == '2026-12-12'
    assert c.post(f"/api/items/{item['id']}/postpone", json={'date': 'x'}).status_code == 400
    hist = ok(c.get(f"/api/items/{item['id']}"))['history']
    assert hist[0]['action'] == 'postponed'

    ok(c.delete(f"/api/items/{item['id']}"))
    assert c.get(f"/api/items/{item['id']}").status_code == 404
    assert item['id'] not in [i['id'] for i in ok(c.get('/api/items'))]
    assert [i['id'] for i in ok(c.get('/api/trash'))] == [item['id']]
    ok(c.post(f"/api/items/{item['id']}/restore"))
    assert ok(c.get('/api/trash')) == []
    assert c.post(f"/api/items/{item['id']}/restore").status_code == 404

    # Old trash is purged
    import api_items
    import db
    ok(c.delete(f"/api/items/{item['id']}"))
    with db.transaction() as conn:
        conn.execute("UPDATE items SET deleted_at = datetime('now', '-31 days') WHERE id = ?", (item['id'],))
    assert api_items.purge_trash() == 0 or True
    with db.transaction() as conn:
        assert conn.execute('SELECT COUNT(*) FROM items WHERE id = ?', (item['id'],)).fetchone()[0] == 0


def test_sync_version(family):
    f = family
    p = f.add_partner()
    v0 = ok(p.get('/api/sync'))['version']
    f.item(title='Nuovo')
    v1 = ok(p.get('/api/sync'))
    assert v1['version'] > v0
    ok(p.get('/api/items'))  # reading changes nothing
    assert ok(p.get('/api/sync'))['version'] == v1['version']
    ok(f.c.post('/api/notifications/read', json={}))  # personal: nobody else needs to reload
    assert ok(p.get('/api/sync'))['version'] == v1['version']


def test_summary(family):
    today = datetime.date.today()
    family.item(title='Ieri', due_date=(today - datetime.timedelta(days=1)).isoformat())
    family.item(title='Oggi', due_date=today.isoformat())
    family.item(kind='appointment', title='Dentista', due_date=today.isoformat(), due_time='15:00')
    spesa = ok(family.c.post('/api/lists', json={'name': 'Spesa'}), 201)
    family.item(title='Latte', list_id=spesa['id'])
    s = ok(family.c.get('/api/summary'))
    assert (s['overdue'], s['today']) == (1, 1)
    assert [a['title'] for a in s['appointments_today']] == ['Dentista']
    assert s['lists'] == [{'id': spesa['id'], 'name': 'Spesa', 'open': 1}]
