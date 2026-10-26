'use strict';
const express = require('express');
const Database = require('better-sqlite3');
const { parse } = require('csv-parse/sync');
const nodemailer = require('nodemailer');
const { ImapFlow } = require('imapflow');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = __dirname;
const DATA = process.env.APP_DATA_DIR || path.join(ROOT, 'data');
const PORT = Number(process.env.PORT || 48173);
fs.mkdirSync(DATA, { recursive: true, mode: 0o700 });
const dbPath = path.join(DATA, 'app.sqlite');
const db = new Database(dbPath);
try { fs.chmodSync(dbPath, 0o600); } catch {}
db.pragma('journal_mode = WAL');
db.exec(`
 CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, company TEXT NOT NULL, contact TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new', source TEXT NOT NULL DEFAULT 'csv', created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(company,email));
 CREATE TABLE IF NOT EXISTS emails(id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL DEFAULT (datetime('now')));
 CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), smtp_host TEXT NOT NULL DEFAULT '', smtp_port INTEGER NOT NULL DEFAULT 465, smtp_secure INTEGER NOT NULL DEFAULT 1, imap_host TEXT NOT NULL DEFAULT '', imap_port INTEGER NOT NULL DEFAULT 993, imap_secure INTEGER NOT NULL DEFAULT 1, account TEXT NOT NULL DEFAULT '', password_ciphertext TEXT NOT NULL DEFAULT '', sender_name TEXT NOT NULL DEFAULT '', signature TEXT NOT NULL DEFAULT '');
 INSERT OR IGNORE INTO settings(id,sender_name,signature) VALUES(1,'Sean','Sean\nMU Group');
`);
const keyPath = path.join(DATA, 'settings.key');
if (!fs.existsSync(keyPath)) fs.writeFileSync(keyPath, crypto.randomBytes(32), { mode: 0o600, flag: 'wx' });
const key = fs.readFileSync(keyPath);
if (key.length !== 32) throw new Error('Invalid local settings key');
function encrypt(secret) { const iv=crypto.randomBytes(12); const c=crypto.createCipheriv('aes-256-gcm',key,iv); const body=Buffer.concat([c.update(secret,'utf8'),c.final()]); return Buffer.concat([iv,c.getAuthTag(),body]).toString('base64'); }
function decrypt(value) { if (!value) return ''; const d=Buffer.from(value,'base64'); const c=crypto.createDecipheriv('aes-256-gcm',key,d.subarray(0,12)); c.setAuthTag(d.subarray(12,28)); return Buffer.concat([c.update(d.subarray(28)),c.final()]).toString('utf8'); }

// Fictional, address-free demo rows. Never treat these as approved leads.
if (db.prepare('SELECT COUNT(*) AS n FROM customers').get().n === 0) {
 const add=db.prepare("INSERT INTO customers(company,contact,email,notes,status,source) VALUES (?,?,'',?,'demo','demo')");
 db.transaction(()=>{ add.run('演示客户 A','采购团队','演示记录；请导入已批准的真实客户。'); add.run('演示客户 B','待确认','演示记录；没有真实邮箱。'); add.run('演示客户 C','待确认','演示记录；不会进入发送队列。'); })();
}
const app=express();
app.disable('x-powered-by');
app.use(express.json({limit:'1mb'}));
app.use('/api/customers/import',express.text({type:['text/csv','text/plain'],limit:'2mb'}));
app.use(express.static(path.join(ROOT,'public')));
const clean=(v,max=500)=>String(v??'').trim().slice(0,max);
const saved=()=>db.prepare('SELECT * FROM settings WHERE id=1').get();
const view=s=>({smtpHost:s.smtp_host,smtpPort:s.smtp_port,smtpSecure:!!s.smtp_secure,imapHost:s.imap_host,imapPort:s.imap_port,imapSecure:!!s.imap_secure,account:s.account,hasPassword:!!s.password_ciphertext,senderName:s.sender_name,signature:s.signature});
function portNumber(v) { const n=Number(v); if(!Number.isInteger(n)||n<1||n>65535) throw new Error('端口必须是 1–65535 的整数'); return n; }
app.get('/api/health',(_q,r)=>r.json({ok:true,service:'foreign-trade-mail-helper'}));
app.get('/api/customers',(_q,r)=>r.json(db.prepare('SELECT id,company,contact,email,notes,status,source,created_at AS createdAt FROM customers ORDER BY id DESC').all()));
app.get('/api/stats',(_q,r)=>r.json({total:db.prepare("SELECT COUNT(*) n FROM customers WHERE status<>'demo'").get().n,pending:db.prepare("SELECT COUNT(*) n FROM emails WHERE status IN ('approved','queued')").get().n,sent:db.prepare("SELECT COUNT(*) n FROM emails WHERE status='sent'").get().n,replied:db.prepare("SELECT COUNT(*) n FROM customers WHERE status='replied'").get().n,bounced:db.prepare("SELECT COUNT(*) n FROM customers WHERE status='bounced'").get().n,sendingEnabled:false}));
app.post('/api/customers/import',(q,r)=>{
 if(typeof q.body!=='string'||!q.body.trim()) return r.status(400).json({error:'请选择 CSV 文件'});
 let rows; try { rows=parse(q.body.replace(/^\uFEFF/,''),{columns:true,skip_empty_lines:true,trim:true}); } catch(e) { return r.status(400).json({error:`CSV 格式错误：${e.message}`}); }
 if(rows.length>5000) return r.status(400).json({error:'单次最多导入 5000 行'});
 if(!['公司名','联系人','邮箱','备注'].every(x=>Object.keys(rows[0]||{}).includes(x))) return r.status(400).json({error:'表头必须包含：公司名,联系人,邮箱,备注'});
 const add=db.prepare("INSERT OR IGNORE INTO customers(company,contact,email,notes,status,source) VALUES (?,?,?,?,'new','csv')"); let added=0,skipped=0; const invalid=[];
 db.transaction(()=>rows.forEach((x,i)=>{const company=clean(x['公司名'],200),contact=clean(x['联系人'],200),email=clean(x['邮箱'],320).toLowerCase(),notes=clean(x['备注'],2000);if(!company||!email||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)){invalid.push(i+2);return;}add.run(company,contact,email,notes).changes?added++:skipped++;}))();
 r.json({added,skipped,invalidRows:invalid});
});
app.get('/api/settings',(_q,r)=>r.json(view(saved())));
app.put('/api/settings',(q,r)=>{try{const b=q.body||{},s=saved(),account=clean(b.account,320);if(account&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(account))throw new Error('邮箱账号格式不正确');const password=typeof b.password==='string'&&b.password?encrypt(b.password):s.password_ciphertext;db.prepare('UPDATE settings SET smtp_host=?,smtp_port=?,smtp_secure=?,imap_host=?,imap_port=?,imap_secure=?,account=?,password_ciphertext=?,sender_name=?,signature=? WHERE id=1').run(clean(b.smtpHost,255),portNumber(b.smtpPort),b.smtpSecure?1:0,clean(b.imapHost,255),portNumber(b.imapPort),b.imapSecure?1:0,account,password,clean(b.senderName,200),clean(b.signature,3000));r.json(view(saved()));}catch(e){r.status(400).json({error:e.message});}});
app.post('/api/settings/test/:kind',async(q,r)=>{const kind=q.params.kind;if(!['smtp','imap'].includes(kind))return r.status(404).json({error:'未知连接类型'});try{const s=saved(),host=kind==='smtp'?s.smtp_host:s.imap_host;if(!host||!s.account||!s.password_ciphertext)throw new Error('missing config');const auth={user:s.account,pass:decrypt(s.password_ciphertext)};if(kind==='smtp'){const t=nodemailer.createTransport({host:s.smtp_host,port:s.smtp_port,secure:!!s.smtp_secure,auth,connectionTimeout:10000,greetingTimeout:10000,socketTimeout:10000});try{await t.verify();}finally{t.close();}}else{const c=new ImapFlow({host:s.imap_host,port:s.imap_port,secure:!!s.imap_secure,auth,logger:false,connectionTimeout:10000,socketTimeout:10000});try{await c.connect();}finally{if(c.usable)await c.logout();}}r.json({ok:true,message:`${kind.toUpperCase()} 连接成功；未发送邮件`});}catch(e){r.status(502).json({ok:false,error:`${kind.toUpperCase()} 连接失败，请检查服务器、端口和应用专用密码（${e.code||'连接错误'}）`});}});
// No generation, send, queue, or inbound polling endpoints exist in this stage.
app.listen(PORT,'127.0.0.1',()=>console.log(`本机服务已启动：http://localhost:${PORT}`));
