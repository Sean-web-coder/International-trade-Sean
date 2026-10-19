import time
import pytest
from fastapi.testclient import TestClient
import web_server
import worker


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
