import json
import time
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
import codex_backend
import server_codex
import web_server
import tasks


def test_device_code_parser_only_exposes_official_prompt():
    prompt = '\n1. Open this link\n\x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n2. Enter this one-time code (expires in 15 minutes)\n  \x1b[94mABCD-EFGH\x1b[0m\n'
    assert server_codex.parse_device_prompt(prompt) == 'ABCD-EFGH'
    assert server_codex.parse_device_prompt(prompt.replace('auth.openai.com', 'evil.example')) is None
    assert server_codex.parse_device_prompt('access_token=secret') is None


def test_server_env_uses_chatgpt_only(monkeypatch, tmp_path):
    monkeypatch.setenv('TRADESCOUT_CODEX_MODE', 'server')
    monkeypatch.setenv('TRADESCOUT_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('TRADESCOUT_ACCESS_TOKEN', 'secret')
    monkeypatch.setenv('OPENAI_API_KEY', 'secret')
    monkeypatch.setenv('CODEX_API_KEY', 'secret')
    result = codex_backend.runtime_environment()
    assert result['CODEX_HOME'] == str(tmp_path / '.codex')
    assert not {'TRADESCOUT_ACCESS_TOKEN', 'OPENAI_API_KEY', 'CODEX_API_KEY'} & result.keys()


def test_api_key_login_is_not_subscription_login():
    with patch.object(server_codex, 'cli_args', return_value=['codex']), patch.object(server_codex.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='', stderr='Logged in using an API key')):
        assert not server_codex.subscription_login()
    with patch.object(server_codex, 'cli_args', return_value=['codex']), patch.object(server_codex.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='', stderr='Logged in using ChatGPT')):
        assert server_codex.subscription_login()


def test_server_login_routes_and_worker(tmp_path, monkeypatch):
    monkeypatch.setenv('TRADESCOUT_CODEX_MODE', 'server')
    monkeypatch.setenv('TRADESCOUT_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('TRADESCOUT_ACCESS_TOKEN', 'test-only-connection-code-123456789')
    manager = server_codex.DeviceLogin()
    ready = threading.Event()
    monkeypatch.setattr(manager, 'authenticated', lambda force=False: ready.is_set())
    monkeypatch.setattr(server_codex, 'login', manager)
    monkeypatch.setattr(tasks, 'execute', lambda job, model: {'ok': True})
    with TestClient(web_server.app) as client:
        assert client.post('/api/codex/login').status_code == 401
        client.headers['Authorization'] = 'Bearer test-only-connection-code-123456789'
        assert client.get('/api/status').json()['mode'] == 'server'
        assert not client.get('/api/status').json()['worker_online']
        ready.set()
        jid = client.post('/api/jobs', json={'kind': 'test'}).json()['id']
        for _ in range(60):
            job = client.get('/api/jobs/'+jid).json()
            if job['state'] == 'done':
                break
            time.sleep(.1)
        assert job['state'] == 'done'
        assert job['result'] == {'ok': True}
        assert client.get('/api/status').json()['worker_online']


def test_device_login_snapshot_does_not_leak_code_after_auth(monkeypatch):
    manager = server_codex.DeviceLogin()
    manager.state = 'pending'
    manager.code = 'ABCD-EFGH'
    manager.deadline = time.time()+900
    monkeypatch.setattr(manager, 'authenticated', lambda force=False: False)
    assert manager.snapshot()['user_code'] == 'ABCD-EFGH'
    monkeypatch.setattr(manager, 'authenticated', lambda force=False: True)
    assert manager.snapshot()['user_code'] is None


def test_login_starts_official_device_flow_without_shell(monkeypatch, tmp_path):
    monkeypatch.setenv('TRADESCOUT_CODEX_MODE', 'server')
    monkeypatch.setenv('TRADESCOUT_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-inherit')
    manager = server_codex.DeviceLogin()
    monkeypatch.setattr(manager, 'authenticated', lambda force=False: False)
    process = SimpleNamespace(poll=lambda: None)
    with patch.object(server_codex, 'command_prefix', return_value=['codex']), patch.object(server_codex.subprocess, 'Popen', return_value=process) as popen, patch.object(server_codex.threading, 'Thread'):
        snapshot = manager.start()
    assert snapshot['state'] == 'starting'
    args, kwargs = popen.call_args
    assert args[0][-2:] == ['login', '--device-auth']
    assert 'forced_login_method="chatgpt"' in args[0]
    assert 'OPENAI_API_KEY' not in kwargs['env']
    assert not kwargs.get('shell')
