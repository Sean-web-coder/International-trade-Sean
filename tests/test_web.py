import time
import pytest
from fastapi.testclient import TestClient
import web_server
import tasks as worker


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('TRADESCOUT_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('TRADESCOUT_ACCESS_TOKEN', 'test-only-connection-code-123456789')
    with TestClient(web_server.app) as c:
        c.headers['Authorization'] = 'Bearer test-only-connection-code-123456789'
        yield c


def test_private_routes_and_public_shell(client):
    assert client.get('/').status_code == 200
    assert client.get('/health').json() == {'ok': True}
    assert client.get('/api/prospects', headers={'Authorization': ''}).status_code == 401
    assert client.post('/api/worker/claim', headers={'Authorization': 'Bearer wrong'}).status_code == 401
    assert client.get('/api/status').json()['worker_online'] is False
    assert client.post('/api/worker/claim').json() == {'job': None}
    assert client.get('/api/status').json()['worker_online'] is True


def test_research_roundtrip_and_draft(client, monkeypatch):
    research = {'company_name': 'Example Buyer', 'evidence': {'multi_category': {'confirmed': True, 'explanation': 'Products', 'sources': ['https://example.com']}}}
    monkeypatch.setattr(worker, 'research_company', lambda *a, **kw: research)
    response = client.post('/api/jobs', json={'kind': 'research', 'website': 'example.com'})
    assert response.status_code == 200
    jid = response.json()['id']
    job = client.post('/api/worker/claim').json()['job']
    result = worker.execute(job, '')
    done = {'lease_token': job['lease_token'], 'result': result}
    assert client.post(f'/api/worker/{jid}/complete', json=done).status_code == 200
    assert client.post(f'/api/worker/{jid}/complete', json=done).status_code == 409
    assert client.get(f'/api/jobs/{jid}').json()['state'] == 'done'
    leads = client.get('/api/prospects').json()
    assert len(leads) == 1 and leads[0]['score'] == 20
    pid = leads[0]['id']
    assert client.patch(f'/api/prospects/{pid}', json={'status': '已回复', 'email': 'buyer@example.com'}).status_code == 200
    jid = client.post('/api/jobs', json={'kind': 'draft', 'prospect_id': pid}).json()['id']
    job = client.post('/api/worker/claim').json()['job']
    assert job['payload']['prospect']['company_name'] == 'Example Buyer'
    draft = {'subject': 'Mixed orders', 'body': 'Do you consolidate sourcing? Sean'}
    monkeypatch.setattr(worker, 'draft_email', lambda *a, **kw: draft)
    assert client.post(f'/api/worker/{jid}/complete', json={'lease_token': job['lease_token'], 'result': worker.execute(job, '')}).status_code == 200
    assert client.get(f'/api/prospects/{pid}/drafts').json() == []
    assert client.post(f'/api/prospects/{pid}/drafts', json={'stage': 0, **draft}).status_code == 200
    assert len(client.get(f'/api/prospects/{pid}/drafts').json()) == 1
    assert client.post(f'/api/prospects/{pid}/drafts', json={'stage': 0, 'subject': 'Hello', 'body': 'word '*51}).status_code == 400


def test_lease_reclaim_rejects_old_worker(client):
    jid = client.post('/api/jobs', json={'kind': 'test'}).json()['id']
    first = client.post('/api/worker/claim').json()['job']
    assert client.post('/api/worker/claim').json()['job'] is None
    with web_server.db() as conn:
        conn.execute('UPDATE jobs SET leased=? WHERE id=?', (time.time()-601, jid))
    second = client.post('/api/worker/claim').json()['job']
    assert first['lease_token'] != second['lease_token']
    assert client.post(f'/api/worker/{jid}/complete', json={'lease_token': first['lease_token'], 'result': {'ok': True}}).status_code == 409
    assert client.delete(f'/api/jobs/{jid}').status_code == 200
    assert client.post(f'/api/worker/{jid}/complete', json={'lease_token': second['lease_token'], 'result': {'ok': True}}).status_code == 409


def test_invalid_tasks_and_failed_codex(client):
    assert client.post('/api/jobs', json={'kind': 'shell'}).status_code == 422
    assert client.post('/api/jobs', json={'kind': 'research', 'website': ''}).status_code == 400
    assert client.post('/api/jobs', json={'kind': 'draft', 'prospect_id': 999}).status_code == 404
    jid = client.post('/api/jobs', json={'kind': 'test'}).json()['id']
    job = client.post('/api/worker/claim').json()['job']
    assert client.post(f'/api/worker/{jid}/complete', json={'lease_token': job['lease_token'], 'error': 'Codex offline'}).status_code == 200
    assert client.get(f'/api/jobs/{jid}').json()['error'] == 'Codex offline'


def test_csv_domain_dedup_and_backup_restore(client):
    csv_data = '公司,国家,官网\nBuyer A,United Arab Emirates,https://www.example.com/catalog\nDuplicate,Saudi Arabia,example.com\nBuyer B,South Africa,https://buyer.test/\nInvalid,Saudi Arabia,not-a-domain\n'
    imported = client.post('/api/prospects/import', content=csv_data, headers={'Content-Type': 'text/plain'})
    assert imported.status_code == 200
    assert imported.json() == {'created': 2, 'duplicates': 1, 'invalid': [5]}
    leads = client.get('/api/prospects').json()
    assert len(leads) == 2
    assert {x['canonical_domain'] for x in leads} == {'example.com', 'buyer.test'}
    first = next(x for x in leads if x['canonical_domain'] == 'example.com')
    assert first['score'] == 0
    assert client.post(f"/api/prospects/{first['id']}/drafts", json={'stage': 0, 'subject': 'Hello', 'body': 'Hello buyer'}).status_code == 200
    backup = client.get('/api/backup').json()
    assert backup['schema_version'] == 1
    assert len(backup['prospects']) == 2
    assert sum(len(x['drafts']) for x in backup['prospects']) == 1
    assert client.post('/api/backup/restore', json=backup).json() == {'created': 0, 'duplicates': 2, 'drafts': 0, 'invalid': 0}


def test_restore_into_new_database_and_legacy_domain_migration(client, tmp_path, monkeypatch):
    import sqlite3
    import storage
    conn = sqlite3.connect(tmp_path / 'old.sqlite3')
    conn.execute('CREATE TABLE prospects (id INTEGER PRIMARY KEY,website TEXT UNIQUE,name TEXT,country TEXT,score INTEGER,status TEXT,email TEXT,contact_name TEXT,research_json TEXT,created_at TEXT,updated_at TEXT)')
    conn.execute('CREATE TABLE drafts (id INTEGER PRIMARY KEY,prospect_id INTEGER,stage INTEGER,subject TEXT,body TEXT,created_at TEXT)')
    for pid, url in ((1, 'https://example.com'), (2, 'https://www.example.com/products')):
        conn.execute('INSERT INTO prospects VALUES (?,?,?,?,?,?,?,?,?,?,?)', (pid,url,'Buyer','UAE',0,'未联系','','','{}','now','now'))
    conn.execute('INSERT INTO drafts VALUES (1,2,0,?,?,?)', ('Hello','Hello buyer','now'))
    conn.commit()
    conn.close()
    migrated = storage.connect(tmp_path / 'old.sqlite3')
    assert len(storage.list_prospects(migrated)) == 1
    assert len(storage.list_drafts(migrated, 1)) == 1
    migrated.close()
    backup = client.get('/api/backup').json()
    monkeypatch.setenv('TRADESCOUT_DATA_DIR', str(tmp_path / 'new'))
    result = client.post('/api/backup/restore', json=backup).json()
    assert result['created'] == len(backup['prospects'])
    assert len(client.get('/api/prospects').json()) == len(backup['prospects'])
