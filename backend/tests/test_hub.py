"""weHub mode: the family comes from weHub (simulated here), existing data is adopted, nothing is lost."""
import pytest
from flask import redirect

import auth
import db
import hub
import oidc
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
                             'members': [{**m, 'role': m.get('role', 'member'), 'level': 'full'} for m in members],
                             'people': list(people)}


def sign_in(c, fake, email, sub=None):
    c.get('/api/oidc/pocketid/login')
    fake.provider.user = {'sub': sub or email, 'email': email, 'email_verified': True, 'name': 'X', 'iss': 'https://id.example'}
    r = c.get('/api/oidc/pocketid/callback?code=x&state=y')
    assert r.status_code == 302
    return r.headers['Location'].split('#/', 1)[1]


def test_sign_in_creates_the_family_from_wehub(client, wehub):
    fil, sara = user(10, 'Fil', 'fil@example.com'), user(11, 'Sara', 'sara@example.com')
    wehub.users = {'fil@example.com': fil, 'sara@example.com': sara}
    family(wehub, members=[{**fil, 'role': 'admin'}, sara],
           people=[{'hub_id': 100, 'name': 'Fil', 'user_hub_id': 10}, {'hub_id': 101, 'name': 'Sara', 'user_hub_id': 11},
                   {'hub_id': 102, 'name': 'Luca', 'kind': 'child', 'user_hub_id': None}])
    wehub.access = {10: [1], 11: [1]}
    c = client()
    assert sign_in(c, wehub, 'fil@example.com') == ''
    me = ok(c.get('/api/me'))
    assert me['user']['name'] == 'Fil' and me['family']['name'] == 'Casa' and me['family']['role'] == 'admin'
    assert [m['name'] for m in me['members']] == ['Fil', 'Sara'] and [p['name'] for p in me['people']] == ['Luca']
    assert me['hub'] == {'url': 'http://wehub.test', 'name': 'weHub'} and me['password_login'] is False and not me['signup_open']
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
    import backup
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
