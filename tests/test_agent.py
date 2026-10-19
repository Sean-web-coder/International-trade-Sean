import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import engine
import codex_backend
import storage


def test_codex_command_and_json(tmp_path):
    def run(command, **kwargs):
        assert command[-1] == '-'
        assert kwargs['input'].endswith('example task')
        assert command[command.index('--sandbox') + 1] == 'read-only'
        assert 'web_search="live"' in command
        assert '--dangerously-bypass-approvals-and-sandbox' not in command
        Path(command[command.index('--output-last-message') + 1]).write_text('{"ok":true}')
        return SimpleNamespace(returncode=0)
    with patch.object(codex_backend, 'command_prefix', return_value=['codex']), patch.object(codex_backend.subprocess, 'run', side_effect=run):
        assert engine.invoke_model('', '', 'JSON', 'example task') == {'ok': True}


def test_cli_failure_redacts_diagnostics():
    with patch.object(codex_backend, 'command_prefix', return_value=['codex']), patch.object(codex_backend.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr='SECRET')):
        with pytest.raises(RuntimeError) as error:
            codex_backend.invoke_codex('JSON', 'test')
        assert 'SECRET' not in str(error.value)


def test_windows_npm_wrapper(tmp_path):
    wrapper = tmp_path / 'codex.cmd'
    entry = tmp_path / 'node_modules/@openai/codex/bin/codex.js'
    entry.parent.mkdir(parents=True)
    entry.touch()
    with patch.object(codex_backend.shutil, 'which', side_effect=[str(wrapper), 'node.exe']):
        assert codex_backend.command_prefix() == ['node.exe', str(entry)]


def test_research_score_and_crm(tmp_path):
    response = {'company_name': 'Example', 'website': 'https://example.com', 'evidence': {
        'multi_category': {'confirmed': True, 'explanation': 'Three categories', 'sources': ['https://example.com/catalog']},
        'china_import': {'confirmed': True, 'explanation': 'No source', 'sources': []}}}
    with patch.object(engine, 'invoke_model', return_value=response):
        result = engine.research_company('', '', 'example.com')
    assert result['score'] == 20
    conn = storage.connect(tmp_path / 'leads.db')
    pid = storage.upsert_prospect(conn, result)
    storage.update_details(conn, pid, '已回复', 'buyer@example.com', 'Buyer')
    assert storage.upsert_prospect(conn, result) == pid
    assert len(storage.list_prospects(conn)) == 1
    assert storage.get_prospect(conn, pid)['status'] == '已回复'
    storage.save_draft(conn, pid, 0, {'subject': 'Mixed sourcing', 'body': 'Do you consolidate orders? Sean'})
    assert len(storage.list_drafts(conn, pid)) == 1
    conn.close()


def test_discovery_dedup_and_invalid_results():
    rows = [{'name': 'Example', 'website': u, 'source_url': 'https://example.com/about'} for u in ['https://www.example.com', 'https://example.com']]
    with patch.object(engine, 'invoke_model', return_value=rows):
        assert len(engine.discover_companies('', '', 'Australia', 'household')) == 1


def test_draft_repair():
    with patch.object(engine, 'invoke_model', side_effect=[{'subject': 'A', 'body': 'word ' * 51}, {'subject': 'Mixed orders', 'body': 'Do you source kitchenware? Sean'}]):
        result = engine.draft_email('', '', {'evidence': {}})
    assert result['warnings'] == []


def test_ui_loads_without_api_key(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(storage, 'DB_PATH', tmp_path / 'ui.db')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py').run()
    assert not app.exception
    assert app.radio[0].value == '本机 Codex（默认）'


def test_ui_research_to_saved_lead(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(storage, 'DB_PATH', tmp_path / 'workflow.db')
    response = {'company_name': 'Example Buyer', 'website': 'https://example.com', 'evidence': {}}
    monkeypatch.setattr(engine, 'invoke_model', lambda *args, **kwargs: response)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py').run()
    next(x for x in app.text_input if x.label == '企业官网').set_value('example.com')
    next(x for x in app.button if x.label == '🔬 联网背调并评分').click().run()
    assert not app.exception
    conn = storage.connect()
    assert storage.list_prospects(conn)[0]['name'] == 'Example Buyer'
    conn.close()
