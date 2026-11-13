"""weHub mode: the family comes from weHub (simulated here), existing data is adopted, nothing is lost."""
import pytest
from flask import redirect

import auth
import db
from famkit import hub
from famkit import oidc
from conftest import PASSWORD, ok, sign_up

KEY = 'k' * 40


class FakeHub:
    """Stands in for weHub's service API."""

    def __init__(self):
        self.users = {}       # (issuer, subject) or email → user
        self.families = {}    # hub id → snapshot
        self.access = {}      # user hub id → [family hub ids]
        self.down = False

    def __call__(self, method, path, payload=None):
        if self.down:
            raise hub.Unavailable('down')
        if path == '/whoami':
            u = self.users.get(payload['email'])
            if not u:
                return {'known': False}
            return {'known': True, 'user': u, 'families': [self.families[f] for f in self.access.get(u['hub_id'], [])]}
        fid = int(path.split('/')[2].split('?')[0])
        snap = self.families.get(fid)
        if snap and f"version={snap['version']}" in path:
            return {'unchanged': True}
        return snap


class FakeProvider:
    user = None

    def authorize_redirect(self, url):
        return redirect('https://id.example/auth')

    def authorize_access_token(self):
        return {'userinfo': self.user}


@pytest.fixture
def wehub(app, monkeypatch):
    fake = FakeHub()
    monkeypatch.setattr(hub, 'URL', 'http://wehub.test')
    monkeypatch.setattr(hub, 'KEY', KEY)
    monkeypatch.setattr(hub, '_call', fake)
    monkeypatch.setattr(auth, 'PASSWORD_LOGIN', False)
    provider = FakeProvider()
    monkeypatch.setattr(oidc, 'PROVIDERS', {'pocketid': 'Pocket ID'})
    monkeypatch.setattr(oidc, '_client', lambda pid: provider)
    fake.provider = provider
    return fake


def user(hub_id, name, email):
    return {'hub_id': hub_id, 'name': name, 'email': email, 'language': 'it'}


def family(fake, hub_id=1, version=1, members=(), people=(), local_id=None, name='Casa'):
    fake.families[hub_id] = {'hub_id': hub_id, 'name': name, 'version': version, 'local_id': local_id,
                             'members': [{**m, 'role': m.get('role', 'member'), 'level': 'full',
                                          'apps': m.get('apps', ['dotrack'])} for m in members],
                             'people': list(people),
                             'apps': [{'id': 'dotrack', 'name': 'doTrack', 'url': 'https://do.example'},
                                      {'id': 'patrack', 'name': 'paTrack', 'url': 'https://pa.example'}]}


def sign_in(c, fake, email, sub=None):
    c.get('/api/oidc/pocketid/login')
    fake.provider.user = {'sub': sub or email, 'email': email, 'email_verified': True, 'name': 'X', 'iss': 'https://id.example'}
    r = c.get('/api/oidc/pocketid/callback?code=x&state=y')
    assert r.status_code == 302
    return r.headers['Location'].split('#/', 1)[1]


def test_sign_in_creates_the_family_from_wehub(client, wehub):
    fil, sara = user(10, 'Fil', 'fil@example.com'), user(11, 'Sara', 'sara@example.com')
    wehub.users = {'fil@example.com': fil, 'sara@example.com': sara}
    family(wehub, members=[{**fil, 'role': 'admin', 'apps': ['dotrack', 'patrack']}, sara],
           people=[{'hub_id': 100, 'name': 'Fil', 'user_hub_id': 10}, {'hub_id': 101, 'name': 'Sara', 'user_hub_id': 11},
                   {'hub_id': 102, 'name': 'Luca', 'kind': 'child', 'user_hub_id': None}])
    wehub.access = {10: [1], 11: [1]}
    c = client()
    assert sign_in(c, wehub, 'fil@example.com') == ''
    me = ok(c.get('/api/me'))
    assert me['user']['name'] == 'Fil' and me['family']['name'] == 'Casa' and me['family']['role'] == 'admin'
    assert [m['name'] for m in me['members']] == ['Fil', 'Sara'] and [p['name'] for p in me['people']] == ['Luca']
    assert me['hub']['url'] == 'http://wehub.test' and me['password_login'] is False and not me['signup_open']
    # The app switcher: the apps Fil may use in this family, this one marked
    assert [(a['id'], a['url'], a['current']) for a in me['hub']['apps']] == [
        ('dotrack', 'https://do.example', True), ('patrack', 'https://pa.example', False)]
    # The partner lands in the same family
    s = client()
    sign_in(s, wehub, 'sara@example.com')
    assert ok(s.get('/api/me'))['family']['id'] == me['family']['id']
    # Changing the family happens in weHub
    assert c.put('/api/family', json={'name': 'X'}).status_code == 409
    assert c.post('/api/family/people', json={'name': 'Nonna'}).status_code == 409
    assert c.post('/api/family/invites').status_code == 409
    assert c.post('/api/login', json={'email': 'fil@example.com', 'password': PASSWORD}).status_code == 403


def test_existing_data_is_adopted(client, wehub, monkeypatch):
    # Before weHub: an account, a family, a person and an item assigned to her
    monkeypatch.setattr(hub, 'URL', '')
    monkeypatch.setattr(auth, 'PASSWORD_LOGIN', True)
    c = client()
    local = sign_up(c)
    nonna = ok(c.post('/api/family/people', json={'name': 'Nonna Anna'}), 201)['id']
    item = ok(c.post('/api/items', json={'title': 'Ritirare la nonna', 'person_id': nonna}), 201)
    monkeypatch.setattr(hub, 'URL', 'http://wehub.test')
    monkeypatch.setattr(auth, 'PASSWORD_LOGIN', False)
    fil = user(10, 'Marco', 'fil@example.com')
    wehub.users = {'fil@example.com': fil}
    family(wehub, local_id=local['family']['id'], name='Famiglia R', members=[{**fil, 'role': 'admin'}],
           people=[{'hub_id': 200, 'name': 'Nonna Anna (mamma)', 'local_id': nonna, 'user_hub_id': None}])
    wehub.access = {10: [1]}
    c2 = client()
    sign_in(c2, wehub, 'fil@example.com')
    me = ok(c2.get('/api/me'))
    assert me['user']['id'] == local['user']['id'] and me['family']['id'] == local['family']['id']
    assert me['family']['name'] == 'Famiglia R' and me['user']['name'] == 'Marco'
    assert me['people'] == [{'id': nonna, 'name': 'Nonna Anna (mamma)'}]
    assert ok(c2.get(f"/api/items/{item['id']}"))['person_id'] == nonna


def test_no_access_and_unknown(client, wehub):
    wehub.users = {'tata@example.com': user(12, 'Tata', 'tata@example.com')}
    assert 'login?error=' in sign_in(client(), wehub, 'tata@example.com')
    assert 'login?error=' in sign_in(client(), wehub, 'nobody@example.com')


def test_wehub_down(client, wehub):
    fil = user(10, 'Fil', 'fil@example.com')
    wehub.users = {'fil@example.com': fil}
    family(wehub, members=[{**fil, 'role': 'admin'}])
    wehub.access = {10: [1]}
    wehub.down = True
    assert 'login?error=' in sign_in(client(), wehub, 'fil@example.com')   # never seen: cannot know
    wehub.down = False
    sign_in(client(), wehub, 'fil@example.com')
    wehub.down = True
    c = client()
    assert sign_in(c, wehub, 'fil@example.com') == ''                       # seen before: goes on
    assert ok(c.get('/api/me'))['family']['name'] == 'Casa'


def test_sync_removes_and_renames(client, wehub):
    fil, sara = user(10, 'Fil', 'fil@example.com'), user(11, 'Sara', 'sara@example.com')
    wehub.users = {'fil@example.com': fil, 'sara@example.com': sara}
    family(wehub, members=[{**fil, 'role': 'admin'}, sara], people=[{'hub_id': 102, 'name': 'Luca', 'user_hub_id': None}])
    wehub.access = {10: [1], 11: [1]}
    c, s = client(), client()
    sign_in(c, wehub, 'fil@example.com')
    sign_in(s, wehub, 'sara@example.com')
    me = ok(c.get('/api/me'))
    sara_id = next(m['id'] for m in me['members'] if m['name'] == 'Sara')
    luca = me['people'][0]['id']
    item = ok(c.post('/api/items', json={'title': 'Spesa', 'assignee_id': sara_id}), 201)
    item2 = ok(c.post('/api/items', json={'title': 'Pediatra', 'person_id': luca}), 201)
    hub.sync_all()   # unchanged version: nothing happens
    assert ok(c.get(f"/api/items/{item['id']}"))['assignee_id'] == sara_id
    # In weHub: Sara loses doTrack, Luca is removed, the family is renamed
    family(wehub, version=2, name='Casa Rossi', members=[{**fil, 'role': 'admin'}])
    hub.sync_all()
    assert ok(c.get(f"/api/items/{item['id']}"))['assignee_id'] is None
    assert ok(c.get(f"/api/items/{item2['id']}"))['person_id'] is None
    me = ok(c.get('/api/me'))
    assert me['family']['name'] == 'Casa Rossi' and [m['name'] for m in me['members']] == ['Fil'] and me['people'] == []
    assert s.get('/api/items').status_code == 401   # signed out
    with db.transaction() as conn:
        assert conn.execute('SELECT COUNT(*) FROM items').fetchone()[0] == 2


def test_export_for_the_import(client, wehub, monkeypatch):
    monkeypatch.setattr(hub, 'URL', '')
    monkeypatch.setattr(auth, 'PASSWORD_LOGIN', True)
    c = client()
    sign_up(c)
    ok(c.post('/api/family/people', json={'name': 'Luca'}), 201)
    assert client().get('/api/hub/export').status_code == 401
    assert client().get('/api/hub/export', headers={'Authorization': 'Bearer wrong'}).status_code == 401
    out = ok(client().get('/api/hub/export', headers={'Authorization': 'Bearer ' + KEY}))
    f = out['families'][0]
    assert f['members'] == [{'email': 'fil@example.com', 'name': 'Fil', 'role': 'admin'}]
    assert [p['name'] for p in f['people']] == ['Luca'] and f['hub_id'] is None


def merge(c, into, families, key=KEY):
    return c.post('/api/hub/merge', json={'into': into, 'families': families}, headers={'Authorization': 'Bearer ' + key})


def test_merge_two_families_made_separately(client, wehub, monkeypatch):
    """Fil and Sara each signed up before weHub: Sara's family is merged into Fil's, nothing is lost."""
    from famkit import backup
    monkeypatch.setattr(hub, 'URL', '')
    monkeypatch.setattr(auth, 'PASSWORD_LOGIN', True)
    fil, sara = client(), client()
    a = sign_up(fil)
    b = sign_up(sara, email='sara@example.com', name='Sara')
    luca_a = ok(fil.post('/api/family/people', json={'name': 'Luca'}), 201)['id']
    luca_b = ok(sara.post('/api/family/people', json={'name': 'luca'}), 201)['id']
    nonna = ok(sara.post('/api/family/people', json={'name': 'Nonna'}), 201)['id']
    la = ok(fil.post('/api/labels', json={'name': 'Casa'}), 201)['id']
    lb = ok(sara.post('/api/labels', json={'name': 'casa'}), 201)['id']
    lst = ok(sara.post('/api/lists', json={'name': 'Spesa Sara'}), 201)['id']
    i1 = ok(sara.post('/api/items', json={'title': 'Pediatra', 'person_id': luca_b, 'labels': [lb]}), 201)['id']
    i2 = ok(sara.post('/api/items', json={'title': 'Visita nonna', 'person_id': nonna}), 201)['id']
    i3 = ok(sara.post(f'/api/lists/{lst}/items', json={'items': ['latte']}), 201)
    ok(fil.post('/api/items', json={'title': 'Bollo', 'labels': [la]}), 201)
    c = client()
    assert merge(c, a['family']['id'], [b['family']['id']], key='wrong').status_code == 401
    r = ok(merge(c, a['family']['id'], [b['family']['id']]))
    assert r['report']['people_merged'] == 1 and r['report']['labels_merged'] == 1 and r['report']['families'] == 1
    assert any(x['name'].startswith('pre-merge') for x in backup.list_backups())
    # Sara is now in Fil's family and sees everything there
    me = ok(sara.get('/api/me'))
    assert me['family']['id'] == a['family']['id'] and {m['name'] for m in me['members']} == {'Fil', 'Sara'}
    assert {p['name'] for p in me['people']} == {'Luca', 'Nonna'}
    assert ok(fil.get(f'/api/items/{i1}'))['person_id'] == luca_a
    assert ok(fil.get(f'/api/items/{i2}'))['person_id'] == nonna
    assert any(x['id'] == lst for x in ok(fil.get('/api/lists')))
    with db.transaction() as conn:
        assert conn.execute('SELECT COUNT(*) FROM families').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM items').fetchone()[0] == 4
        assert conn.execute('SELECT label_id FROM item_labels WHERE item_id = ?', (i1,)).fetchone()[0] == la
    # Nothing left to merge, and a family linked to weHub cannot be merged away
    assert merge(c, a['family']['id'], [b['family']['id']]).status_code == 404
    assert merge(c, a['family']['id'], []).status_code == 400


def test_other_apps_add_to_lists_through_wehub(client, wehub):
    """eaTrack → weHub → doTrack: the shopping lists of a weHub family, and entries added as the member who sent them."""
    fil, sara = user(10, 'Fil', 'fil@example.com'), user(11, 'Sara', 'sara@example.com')
    wehub.users = {'fil@example.com': fil, 'sara@example.com': sara}
    family(wehub, hub_id=7, members=[{**fil, 'role': 'admin'}, sara])
    wehub.access = {10: [7], 11: [7]}
    H = {'Authorization': 'Bearer ' + KEY}
    assert client().get('/api/hub/families/7/lists', headers=H).status_code == 404   # nobody signed in yet
    c = client()
    sign_in(c, wehub, 'fil@example.com')
    sign_in(client(), wehub, 'sara@example.com')
    spesa = ok(c.post('/api/lists', json={'name': 'Spesa', 'kind': 'checklist'}), 201)['id']
    ok(c.post('/api/lists', json={'name': 'Progetto', 'kind': 'project'}), 201)
    assert client().get('/api/hub/families/7/lists').status_code == 401
    assert client().get('/api/hub/families/7/lists', headers={'Authorization': 'Bearer dt_x'}).status_code == 401
    lists = ok(client().get('/api/hub/families/7/lists', headers=H))
    assert 'Progetto' not in [x['name'] for x in lists] and spesa in [x['id'] for x in lists]
    r = ok(client().post(f'/api/hub/families/7/lists/{spesa}/items?user=11', headers=H, json={'items': ['Zucchine', '2 kg mele']}), 201)
    assert [i['title'] for i in r['added']] == ['Zucchine', 'mele'] and r['skipped'] == []
    sara_id = next(m['id'] for m in ok(c.get('/api/me'))['members'] if m['name'] == 'Sara')
    assert {i['created_by'] for i in r['added']} == {sara_id}
    r = ok(client().post(f'/api/hub/families/7/lists/{spesa}/items', headers=H, json={'items': ['zucchine', 'Pane']}), 201)
    assert r['skipped'] == ['zucchine'] and [i['title'] for i in r['added']] == ['Pane']
    # Another family's list is not reachable
    assert client().post('/api/hub/families/7/lists/99999/items', headers=H, json={'items': ['x']}).status_code == 404


def _hub_family_with_luca(client, wehub):
    fil, sara = user(10, 'Fil', 'fil@example.com'), user(11, 'Sara', 'sara@example.com')
    wehub.users = {'fil@example.com': fil, 'sara@example.com': sara}
    family(wehub, hub_id=7, members=[{**fil, 'role': 'admin'}, sara],
           people=[{'hub_id': 100, 'name': 'Fil', 'user_hub_id': 10}, {'hub_id': 102, 'name': 'Luca', 'kind': 'child', 'user_hub_id': None}])
    wehub.access = {10: [7], 11: [7]}
    c = client()
    sign_in(c, wehub, 'fil@example.com')
    return c


def test_patrack_keeps_a_document_deadline_in_step(client, wehub):
    c = _hub_family_with_luca(client, wehub)
    H = {'Authorization': 'Bearer ' + KEY}
    put = lambda ref, **d: client().put(f'/api/hub/families/7/deadlines/{ref}?user=10&from=patrack', headers=H, json=d)  # noqa: E731
    doc = {'title': "Carta d'identità", 'due_date': '2031-03-04', 'remind_days': 60, 'category': 'identity',
           'person_hub_id': 102, 'url': 'https://pa.example/#/doc/12', 'notes': 'paTrack'}
    assert put('patrack-12').status_code == 400 and put('other-12', **doc).status_code == 400
    r = ok(put('patrack-12', **doc), 201)
    item = ok(c.get(f"/api/items/{r['item_id']}"))
    luca = next(p['id'] for p in ok(c.get('/api/me'))['people'] if p['name'] == 'Luca')
    assert (item['kind'], item['title'], item['due_date'], item['remind_days'], item['category'], item['person_id']) == \
        ('deadline', "Carta d'identità", '2031-03-04', 60, 'documents', luca)
    assert item['ext_url'] == 'https://pa.example/#/doc/12' and item['ext_ref'] == 'patrack-12'
    # Things added in doTrack stay; paTrack's fields follow the document; done + new expiry = open again
    ok(c.put(f"/api/items/{item['id']}", json={**item, 'priority': 1, 'notes': 'portare foto'}))
    ok(c.post(f"/api/items/{item['id']}/done"))
    r2 = ok(put('patrack-12', **{**doc, 'due_date': '2041-03-04', 'member_hub_id': 10, 'url': 'javascript:x'}))
    assert r2 == {'item_id': item['id'], 'created': False}
    item = ok(c.get(f"/api/items/{item['id']}"))
    fil = ok(c.get('/api/me'))['user']['id']
    assert (item['due_date'], item['priority'], item['notes'], item['done'], item['assignee_id'], item['person_id']) == \
        ('2041-03-04', 1, 'portare foto', False, fil, None)
    assert item['ext_url'] == 'https://pa.example/#/doc/12'
    # Deleted by someone in doTrack: not created again, paTrack is told
    ok(c.delete(f"/api/items/{item['id']}"))
    assert ok(put('patrack-12', **doc)) == {'item_id': item['id'], 'deleted': True}
    # Asked by paTrack to remove it: to the trash, and the reference is free for a new one
    r = ok(put('patrack-13', **doc), 201)
    assert ok(client().delete('/api/hub/families/7/deadlines/patrack-13?user=10', headers=H)) == {'ok': True}
    assert c.get(f"/api/items/{r['item_id']}").status_code == 404
    assert ok(put('patrack-13', **doc), 201)['item_id'] != r['item_id']
    assert client().put('/api/hub/families/7/deadlines/patrack-14', json=doc).status_code == 401


def test_a_deadline_document_goes_to_patrack(client, wehub, monkeypatch):
    import io
    import requests
    c = _hub_family_with_luca(client, wehub)
    luca = next(p['id'] for p in ok(c.get('/api/me'))['people'] if p['name'] == 'Luca')
    item = ok(c.post('/api/items', json={'kind': 'deadline', 'title': 'Passaporto Luca', 'due_date': '2030-05-01',
                                         'remind_days': 90, 'person_id': luca, 'category': 'documents'}), 201)
    calls = []

    class R:
        status_code = 201
        def json(self): return {'id': 55, 'url': 'https://pa.example/#/doc/55'}

    monkeypatch.setattr(requests, 'request', lambda method, url, **kw: calls.append((method, url, kw)) or R())
    send = lambda i: c.post(f'/api/items/{i}/to-patrack', data={'file': (io.BytesIO(b'%PDF-1.4 x'), 'passaporto.pdf')})  # noqa: E731
    r = ok(send(item['id']), 201)
    assert r['ext_ref'] == 'patrack-55' and r['ext_url'] == 'https://pa.example/#/doc/55' and r['attachments'] == []
    method, url, kw = calls[0]
    assert (method, url) == ('POST', 'http://wehub.test/api/service/apps/patrack/families/7/documents')
    p = kw['json']
    assert (p['file_name'], p['expiry_date'], p['remind_days'], p['person_hub_id'], p['category'], p['dotrack_item']) == \
        ('passaporto.pdf', '2030-05-01', 90, 102, 'identity', item['id'])
    assert kw['params'] == {'user': 10}
    assert send(item['id']).status_code == 409                       # it already has its document
    task = ok(c.post('/api/items', json={'title': 'Comprare latte'}), 201)
    assert send(task['id']).status_code == 400                       # only deadlines

    class Refused:
        status_code = 403
        def json(self): return {'error': 'You do not use paTrack in this family'}
    monkeypatch.setattr(requests, 'request', lambda method, url, **kw: Refused())
    other = ok(c.post('/api/items', json={'kind': 'deadline', 'title': 'Bollo', 'due_date': '2030-01-31'}), 201)
    r = send(other['id'])
    assert r.status_code == 403 and r.get_json()['error'] == 'Non usi paTrack in questa famiglia'


def test_summary_for_wehub_home(client, wehub):
    import datetime
    c = _hub_family_with_luca(client, wehub)
    d = lambda n: (datetime.date.today() + datetime.timedelta(days=n)).isoformat()  # noqa: E731
    me = ok(c.get('/api/me'))['user']['id']
    for title, due, extra in (('Bollo', d(-1), {'kind': 'deadline'}), ('Pediatra', d(0), {'kind': 'appointment', 'due_time': '16:30'}),
                              ('Mio', d(0), {'assignee_id': me}), ('Condominio', d(5), {}), ('Lontano', d(30), {}), ('Senza data', None, {})):
        ok(c.post('/api/items', json={'title': title, 'due_date': due, **extra}), 201)
    spesa = ok(c.post('/api/lists', json={'name': 'Spesa', 'kind': 'checklist'}), 201)['id']
    ok(c.post('/api/items', json={'title': 'Latte', 'due_date': d(0), 'list_id': spesa}), 201)
    H = {'Authorization': 'Bearer ' + KEY}
    assert client().get('/api/hub/families/7/summary?user=10').status_code == 401
    s = ok(client().get('/api/hub/families/7/summary?user=10', headers=H))
    assert (s['overdue'], s['today'], s['week']) == (1, 2, 1)
    assert [i['title'] for i in s['items']] == ['Bollo', 'Pediatra', 'Mio', 'Condominio']   # by date, timed first
    assert next(i for i in s['items'] if i['title'] == 'Mio')['mine'] is True
