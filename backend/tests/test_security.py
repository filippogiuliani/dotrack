"""Two-step verification, signing out elsewhere, API tokens, webhooks, password sign-in switch."""
import hashlib
import hmac
import json
import time

import auth
import security
import webhooks
from conftest import PASSWORD, ok


def login(c, email='fil@example.com', password=PASSWORD):
    return c.post('/api/login', json={'email': email, 'password': password})


def test_totp_algorithm():
    # RFC 6238 test vector (SHA-1, secret "12345678901234567890"), last 6 digits
    import base64
    secret = base64.b32encode(b'12345678901234567890').decode()
    assert security.totp(secret, 59) == '287082'
    assert security.totp(secret, 1111111109) == '081804'


def test_two_step_verification(family, client):
    c = family.c
    assert ok(c.get('/api/account/2fa')) == {'enabled': False, 'recovery_left': 0}
    s = ok(c.post('/api/account/2fa/setup'))
    assert s['uri'].startswith('otpauth://totp/doTrack:') and s['qr'].startswith('data:image/svg+xml;base64,')
    secret = s['secret'].replace(' ', '')
    assert c.post('/api/account/2fa/enable', json={'code': '000000'}).status_code == 400
    r = ok(c.post('/api/account/2fa/enable', json={'code': security.totp(secret)}))
    assert r['enabled'] and len(r['recovery_codes']) == 10 and r['recovery_left'] == 10
    assert ok(c.get('/api/me'))['user']['two_factor']

    # Signing in now takes a code
    d = client()
    assert ok(login(d)) == {'two_factor': True}
    assert d.get('/api/items').status_code == 401  # not signed in yet
    assert d.post('/api/login/2fa', json={'code': '123456'}).status_code == 401
    security._last_used.clear()
    ok(d.post('/api/login/2fa', json={'code': security.totp(secret)}))
    assert ok(d.get('/api/me'))['authenticated']
    # A code works once
    e = client()
    ok(login(e))
    assert e.post('/api/login/2fa', json={'code': security.totp(secret)}).status_code == 401
    # A recovery code works once
    ok(e.post('/api/login/2fa', json={'code': r['recovery_codes'][0]}))
    f2 = client()
    ok(login(f2))
    assert f2.post('/api/login/2fa', json={'code': r['recovery_codes'][0]}).status_code == 401
    assert ok(c.get('/api/account/2fa'))['recovery_left'] == 9

    # Turning it off needs the password (or a code)
    assert c.post('/api/account/2fa/disable', json={'password': 'nope'}).status_code == 400
    ok(c.post('/api/account/2fa/disable', json={'password': PASSWORD}))
    assert ok(login(client())) == {'ok': True}


def test_second_step_expires(family, client, monkeypatch):
    s = ok(family.c.post('/api/account/2fa/setup'))
    ok(family.c.post('/api/account/2fa/enable', json={'code': security.totp(s['secret'].replace(' ', ''))}))
    d = client()
    ok(login(d))
    real = time.time
    monkeypatch.setattr(time, 'time', lambda: real() + 400)
    assert d.post('/api/login/2fa', json={'code': '000000'}).status_code == 401


def test_sign_out_elsewhere(family, client):
    other = client()
    ok(login(other))
    ok(family.c.post('/api/account/sessions/revoke'))
    assert other.get('/api/items').status_code == 401
    assert family.c.get('/api/items').status_code == 200


def test_api_tokens(family, client):
    c = family.c
    t = ok(c.post('/api/account/tokens', json={'name': 'Home Assistant'}), 201)
    assert t['token'].startswith('dt_')
    listed = ok(c.get('/api/account/tokens'))
    assert listed[0]['name'] == 'Home Assistant' and t['token'] not in json.dumps(listed)
    api = client()
    h = {'Authorization': 'Bearer ' + t['token']}
    assert api.get('/api/items').status_code == 401
    assert api.get('/api/items', headers=h).status_code == 200
    spesa = ok(c.post('/api/lists', json={'name': 'Spesa'}), 201)
    ok(api.post(f"/api/lists/{spesa['id']}/items", json={'items': ['latte']}, headers=h), 201)
    assert ok(api.get('/api/summary', headers=h))['lists'][0]['open'] == 1
    # Not for account or security changes
    assert api.get('/api/account/tokens', headers=h).status_code == 403
    assert api.delete('/api/account', json={'password': PASSWORD}, headers=h).status_code == 403
    assert api.post('/api/caldav/passwords', json={}, headers=h).status_code == 403
    assert api.get('/api/items', headers={'Authorization': 'Bearer dt_wrong'}).status_code == 401
    # Revoked
    ok(c.delete(f"/api/account/tokens/{listed[0]['id']}"))
    assert api.get('/api/items', headers=h).status_code == 401


def test_webhooks(family, monkeypatch):
    sent = []
    monkeypatch.setattr(webhooks, 'send', lambda hooks: sent.extend(hooks))
    f = family
    p = f.add_partner()
    assert p.post('/api/family/webhooks', json={'url': 'https://x.example/hook'}).status_code == 403  # admin only
    assert f.c.post('/api/family/webhooks', json={'url': 'ftp://x'}).status_code == 400
    assert f.c.post('/api/family/webhooks', json={'url': 'https://x.example/h', 'events': ['nope']}).status_code == 400
    r = ok(f.c.post('/api/family/webhooks', json={'url': 'https://x.example/hook', 'events': ['item.created', 'item.done']}), 201)
    secret = r['secret']
    item = f.item(title='Latte')
    ok(f.c.put(f"/api/items/{item['id']}", json={**item, 'title': 'Latte intero'}))  # not subscribed
    ok(f.c.post(f"/api/items/{item['id']}/done"))
    events = [json.loads(b)['event'] for _, _, _, b in sent]
    assert events == ['item.created', 'item.done']
    hook_id, url, key, body = sent[0]
    assert key == secret and json.loads(body)['data']['title'] == 'Latte'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert len(sig) == 64
    ok(f.c.delete(f"/api/family/webhooks/{hook_id}"))
    assert ok(f.c.get('/api/family/webhooks')) == []


def test_password_sign_in_can_be_turned_off(family, client, monkeypatch):
    monkeypatch.setattr(auth, 'PASSWORD_LOGIN', False)
    assert login(client()).status_code == 403
    assert client().post('/api/signup', json={'name': 'X', 'email': 'x@example.com', 'password': PASSWORD, 'consent': True}).status_code == 403
    assert ok(client().get('/api/me'))['password_login'] is False
