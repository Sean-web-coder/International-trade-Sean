"""Single-owner hosted web app. Local Codex workers poll authenticated jobs."""
from __future__ import annotations
import hmac
import csv
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import threading
from contextlib import asynccontextmanager
from contextlib import closing
from typing import Literal

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import storage
from engine import normalize_url, score_prospect, qualify_score, validate_draft

@asynccontextmanager
async def lifespan(app):
    from server_codex import server_mode, prepare_home, login
    stop = threading.Event()
    thread = None
    if server_mode():
        prepare_home()
        thread = threading.Thread(target=server_job_loop, args=(stop,), daemon=True)
        thread.start()
    yield
    stop.set()
    if server_mode():
        login.stop_login()


app = FastAPI(title="TradeScout Web", docs_url=None, redoc_url=None, lifespan=lifespan)
ROOT = Path(__file__).resolve().parent


def db():
    directory = Path(os.getenv("TRADESCOUT_DATA_DIR", str(ROOT / "data")))
    conn = storage.connect(None if os.getenv('DATABASE_URL') else directory / 'leads.sqlite3')
    conn.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
        state TEXT NOT NULL, result TEXT, error TEXT, created REAL NOT NULL,
        leased REAL, lease_token TEXT)''')
    conn.execute('CREATE TABLE IF NOT EXISTS worker_status (id INTEGER PRIMARY KEY, seen REAL NOT NULL)')
    conn.commit()
    return conn


def authorize(authorization: str = Header(default="")):
    expected = os.getenv("TRADESCOUT_ACCESS_TOKEN", "")
    if len(expected) < 24:
        raise HTTPException(503, "请在服务器设置至少 24 字符的 TRADESCOUT_ACCESS_TOKEN")
    supplied = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "连接码不正确")


@app.get("/")
def index():
    return FileResponse(ROOT / "web/index.html", headers={"Cache-Control": "no-store"})


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/status", dependencies=[Depends(authorize)])
def status():
    from server_codex import server_mode, login
    if server_mode():
        auth = login.snapshot()
        return {"mode": "server", "worker_online": auth["authenticated"], "codex": auth,
                "storage": "postgres" if os.getenv('DATABASE_URL') else "temporary"}
    with closing(db()) as conn:
        row = conn.execute('SELECT seen FROM worker_status WHERE id=1').fetchone()
    return {"mode": "local", "worker_online": bool(row and time.time() - row[0] < 30),
            "storage": "postgres" if os.getenv('DATABASE_URL') else "temporary"}


class JobRequest(BaseModel):
    kind: Literal["discover", "research", "draft", "test"]
    country: str = Field(default="Australia", max_length=100)
    niche: str = Field(default="household goods, kitchenware, gifts", max_length=1000)
    limit: int = Field(default=3, ge=1, le=10)
    website: str = Field(default="", max_length=2000)
    context: str = Field(default="", max_length=2000)
    prospect_id: int | None = None
    stage: int = Field(default=0, ge=0, le=2)


@app.post("/api/jobs", dependencies=[Depends(authorize)])
def create_job(request: JobRequest):
    payload = request.model_dump()
    with closing(db()) as conn:
        if request.kind == 'research':
            try:
                payload['website'] = normalize_url(request.website)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        if request.kind == 'draft':
            record = storage.get_prospect(conn, request.prospect_id or 0)
            if not record:
                raise HTTPException(404, '请先选择已背调客户')
            payload['prospect'] = storage.approved_research(conn, record['id'])
        if conn.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0] >= 20:
            raise HTTPException(429, '待处理任务过多，请等待或取消旧任务')
        jid = secrets.token_hex(16)
        conn.execute('INSERT INTO jobs (id,kind,payload,state,created) VALUES (?,?,?,?,?)',
                     (jid, request.kind, json.dumps(payload, ensure_ascii=False), 'queued', time.time()))
        conn.commit()
    return {'id': jid}


@app.get('/api/jobs/{jid}', dependencies=[Depends(authorize)])
def get_job(jid: str):
    with closing(db()) as conn:
        row = conn.execute('SELECT state,result,error FROM jobs WHERE id=?', (jid,)).fetchone()
    if not row:
        raise HTTPException(404, '任务不存在')
    return {'state': row['state'], 'result': json.loads(row['result']) if row['result'] else None, 'error': row['error']}


@app.delete('/api/jobs/{jid}', dependencies=[Depends(authorize)])
def cancel_job(jid: str):
    with closing(db()) as conn:
        conn.execute("UPDATE jobs SET state='cancelled' WHERE id=? AND state IN ('queued','running')", (jid,))
        conn.commit()
    return {'ok': True}


@app.post('/api/worker/claim', dependencies=[Depends(authorize)])
def claim():
    now = time.time()
    with closing(db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('INSERT INTO worker_status (id,seen) VALUES (1,?) ON CONFLICT(id) DO UPDATE SET seen=excluded.seen', (now,))
        conn.execute("UPDATE jobs SET state='error',error='任务等待超过一小时，请重新提交' WHERE state='queued' AND created<?", (now-3600,))
        lock = ' FOR UPDATE SKIP LOCKED' if os.getenv('DATABASE_URL') else ''
        row = conn.execute("SELECT * FROM jobs WHERE state='queued' OR (state='running' AND leased<?) ORDER BY created LIMIT 1" + lock, (now-600,)).fetchone()
        if not row:
            conn.commit()
            return {'job': None}
        lease = secrets.token_hex(16)
        conn.execute("UPDATE jobs SET state='running',leased=?,lease_token=? WHERE id=?", (now, lease, row['id']))
        conn.commit()
        return {'job': {'id': row['id'], 'kind': row['kind'], 'payload': json.loads(row['payload']), 'lease_token': lease}}


@app.post('/api/worker/heartbeat', dependencies=[Depends(authorize)])
def heartbeat():
    with closing(db()) as conn:
        conn.execute('INSERT INTO worker_status (id,seen) VALUES (1,?) ON CONFLICT(id) DO UPDATE SET seen=excluded.seen', (time.time(),))
        conn.commit()
    return {'ok': True}


class Completion(BaseModel):
    lease_token: str
    result: dict | list | None = None
    error: str | None = Field(default=None, max_length=500)


@app.post('/api/worker/{jid}/complete', dependencies=[Depends(authorize)])
def complete(jid: str, value: Completion):
    with closing(db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        lock = ' FOR UPDATE' if os.getenv('DATABASE_URL') else ''
        row = conn.execute('SELECT * FROM jobs WHERE id=?' + lock, (jid,)).fetchone()
        if not row or row['state'] != 'running' or row['lease_token'] != value.lease_token:
            raise HTTPException(409, '任务已结束或已重新分配')
        result = value.result
        if not value.error:
            if row['kind'] == 'research':
                if not isinstance(result, dict) or not isinstance(result.get('evidence'), dict):
                    raise HTTPException(422, '背调结果格式错误')
                result['score'] = 0
                result['score_parts'] = {key: 0 for key in score_prospect(result['evidence'])[1]}
                result['priority'] = qualify_score(0)
                result['input_website'] = json.loads(row['payload'])['website']
                storage.upsert_prospect(conn, result)
            elif row['kind'] == 'draft':
                if not isinstance(result, dict) or not isinstance(result.get('subject'), str) or not isinstance(result.get('body'), str):
                    raise HTTPException(422, '草稿格式错误')
            elif row['kind'] == 'discover' and not isinstance(result, list):
                raise HTTPException(422, '搜索结果格式错误')
        conn.execute('UPDATE jobs SET state=?,result=?,error=? WHERE id=?',
                     ('error' if value.error else 'done', json.dumps(result, ensure_ascii=False), value.error, jid))
        conn.commit()
    return {'ok': True}


@app.get('/api/prospects', dependencies=[Depends(authorize)])
def prospects():
    with closing(db()) as conn:
        return storage.list_prospects(conn)


@app.post('/api/prospects/import', dependencies=[Depends(authorize)])
def import_prospects(content: str = Body(media_type='text/plain')):
    if len(content.encode('utf-8')) > 1_000_000:
        raise HTTPException(413, 'CSV 不得超过 1 MB')
    try:
        rows = list(csv.DictReader(io.StringIO(content.lstrip('\ufeff'))))
    except csv.Error as exc:
        raise HTTPException(400, 'CSV 格式错误') from exc
    if not rows or len(rows) > 500:
        raise HTTPException(400, '每次请导入 1–500 行客户')
    result = {'created': 0, 'duplicates': 0, 'invalid': []}
    with closing(db()) as conn:
        for index, row in enumerate(rows, 2):
            website = next((row.get(k, '').strip() for k in ('website', 'url', '官网', '网站') if row.get(k)), '')
            name = next((row.get(k, '').strip() for k in ('name', 'company', '公司', '公司名称') if row.get(k)), '')
            country = next((row.get(k, '').strip() for k in ('country', '国家') if row.get(k)), '')
            try:
                domain = storage.canonical_domain(website)
            except ValueError:
                result['invalid'].append(index)
                continue
            if conn.execute('SELECT 1 FROM prospects WHERE canonical_domain=?', (domain,)).fetchone():
                result['duplicates'] += 1
                continue
            storage.upsert_prospect(conn, {'website': website, 'name': name or domain, 'country': country,
                                           'import_source': 'CSV', 'evidence': {}}, commit=False)
            result['created'] += 1
        conn.commit()
    return result


@app.get('/api/backup', dependencies=[Depends(authorize)])
def backup():
    with closing(db()) as conn:
        prospects = storage.list_prospects(conn)
        for record in prospects:
            record['drafts'] = storage.list_drafts(conn, record['id'])
            record['evidence_reviews'] = [dict(r) for r in conn.execute(
                'SELECT * FROM evidence_reviews WHERE prospect_id=?', (record['id'],)).fetchall()]
    return {'schema_version': 1, 'exported_at': time.time(), 'prospects': prospects}


@app.post('/api/backup/restore', dependencies=[Depends(authorize)])
def restore_backup(payload: dict):
    if payload.get('schema_version') not in (None, 1) or not isinstance(payload.get('prospects'), list):
        raise HTTPException(400, '备份格式不正确')
    rows = payload['prospects']
    if len(rows) > 10000:
        raise HTTPException(413, '备份记录过多')
    result = {'created': 0, 'duplicates': 0, 'drafts': 0, 'invalid': 0}
    with closing(db()) as conn:
        for row in rows:
            if not isinstance(row, dict):
                result['invalid'] += 1
                continue
            try:
                domain = storage.canonical_domain(row.get('website', ''))
            except ValueError:
                result['invalid'] += 1
                continue
            existing = conn.execute('SELECT id FROM prospects WHERE canonical_domain=?', (domain,)).fetchone()
            if existing:
                pid = existing['id']
                result['duplicates'] += 1
            else:
                data = json.loads(row.get('research_json') or '{}')
                if not isinstance(data, dict):
                    data = {}
                data.update({'website': row['website'], 'input_website': row['website'],
                             'company_name': row.get('name') or domain,
                             'country': row.get('country') or '', 'score': 0})
                pid = storage.upsert_prospect(conn, data, commit=False)
                conn.execute('UPDATE prospects SET status=?,email=?,contact_name=? WHERE id=?',
                             (row.get('status') or '未联系', row.get('email') or '', row.get('contact_name') or '', pid))
                result['created'] += 1
            for draft in row.get('drafts', []):
                if not isinstance(draft, dict) or not {'subject', 'body', 'stage'} <= draft.keys():
                    continue
                found = conn.execute('SELECT 1 FROM drafts WHERE prospect_id=? AND stage=? AND subject=? AND body=?',
                                     (pid, draft['stage'], draft['subject'], draft['body'])).fetchone()
                if not found:
                    storage.save_draft(conn, pid, int(draft['stage']), draft, commit=False)
                    result['drafts'] += 1
            for review in row.get('evidence_reviews', []):
                if not isinstance(review, dict) or review.get('criterion') not in storage.SCORING:
                    continue
                if review.get('decision') not in {'approved', 'rejected', 'pending'}:
                    continue
                conn.execute('''INSERT INTO evidence_reviews (prospect_id,criterion,decision,source_url,reviewed_at)
                                VALUES (?,?,?,?,?) ON CONFLICT(prospect_id,criterion) DO NOTHING''',
                             (pid, review['criterion'], review['decision'], review.get('source_url') or '',
                              review.get('reviewed_at') or ''))
            storage.recompute_score(conn, pid, commit=False)
        conn.commit()
    return result


class Details(BaseModel):
    status: Literal['未联系', '已发首封', '已跟进一次', '已跟进两次', '已回复', '已询盘', '已成交', '暂停']
    email: str = Field(default='', max_length=320)
    contact_name: str = Field(default='', max_length=200)


@app.patch('/api/prospects/{pid}', dependencies=[Depends(authorize)])
def details(pid: int, value: Details):
    with closing(db()) as conn:
        if not storage.get_prospect(conn, pid):
            raise HTTPException(404, '客户不存在')
        storage.update_details(conn, pid, value.status, value.email, value.contact_name)
    return {'ok': True}


@app.get('/api/prospects/{pid}/evidence', dependencies=[Depends(authorize)])
def evidence(pid: int):
    with closing(db()) as conn:
        result = storage.evidence_state(conn, pid)
    if result is None:
        raise HTTPException(404, '客户不存在')
    return result


class EvidenceReview(BaseModel):
    criterion: str
    decision: Literal['approved', 'rejected', 'pending']
    source_url: str = Field(default='', max_length=2000)


@app.post('/api/prospects/{pid}/evidence', dependencies=[Depends(authorize)])
def save_evidence_review(pid: int, value: EvidenceReview):
    with closing(db()) as conn:
        try:
            score = storage.review_evidence(conn, pid, value.criterion, value.decision, value.source_url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {'score': score}


class Draft(BaseModel):
    stage: int = Field(ge=0, le=2)
    subject: str = Field(max_length=500)
    body: str = Field(max_length=5000)


@app.post('/api/prospects/{pid}/drafts', dependencies=[Depends(authorize)])
def save_draft(pid: int, value: Draft):
    issues = validate_draft(value.subject, value.body)
    if issues:
        raise HTTPException(400, '；'.join(issues))
    with closing(db()) as conn:
        if not storage.get_prospect(conn, pid):
            raise HTTPException(404, '客户不存在')
        storage.save_draft(conn, pid, value.stage, value.model_dump())
    return {'ok': True}


@app.get('/api/prospects/{pid}/drafts', dependencies=[Depends(authorize)])
def drafts(pid: int):
    with closing(db()) as conn:
        return storage.list_drafts(conn, pid)


@app.post('/api/codex/login', dependencies=[Depends(authorize)])
def start_codex_login():
    from server_codex import server_mode, login
    if not server_mode():
        raise HTTPException(409, '当前部署未启用服务器 Codex')
    return login.start()


@app.post('/api/codex/logout', dependencies=[Depends(authorize)])
def logout_codex():
    from server_codex import server_mode, login
    if not server_mode():
        raise HTTPException(409, '当前部署未启用服务器 Codex')
    # Do not revoke credentials while a model job is still running.
    with closing(db()) as conn:
        if conn.execute("SELECT 1 FROM jobs WHERE state='running' LIMIT 1").fetchone():
            raise HTTPException(409, '请等待当前任务结束后再退出 Codex')
    try:
        return login.logout()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


def server_job_loop(stop):
    from server_codex import login
    from tasks import execute
    while not stop.is_set():
        if not login.authenticated():
            stop.wait(3)
            continue
        try:
            job = claim()['job']
            if not job:
                stop.wait(2)
                continue
            try:
                result = execute(job, os.getenv('CODEX_MODEL', ''))
                value = Completion(lease_token=job['lease_token'], result=result)
            except Exception:
                value = Completion(lease_token=job['lease_token'], error='服务器 Codex 执行失败。请检查登录、订阅额度、模型权限或网络后重试。')
            try:
                complete(job['id'], value)
            except HTTPException as exc:
                if exc.status_code == 422:
                    complete(job['id'], Completion(lease_token=job['lease_token'], error='Codex 返回格式不正确，请重试。'))
                elif exc.status_code != 409:
                    raise
        except Exception:
            # Never print model prompts, tokens or CLI output to server logs.
            stop.wait(3)
