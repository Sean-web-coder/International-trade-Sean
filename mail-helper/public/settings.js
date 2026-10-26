'use strict';
const form=document.getElementById('settings'),out=document.getElementById('result');
async function json(url,options){const r=await fetch(url,options);const d=await r.json();if(!r.ok)throw new Error(d.error||'请求失败');return d;}
async function load(){try{const s=await json('/api/settings');for(const [key,value] of Object.entries(s)){if(key==='hasPassword')continue;const el=form.elements[key];if(el)el.type==='checkbox'?el.checked=value:el.value=value;}document.getElementById('passwordState').textContent=s.hasPassword?'应用专用密码已保存（不显示明文）':'尚未保存应用专用密码';}catch(e){out.textContent=e.message;}}
document.getElementById('gmail').onclick=()=>{for(const [k,v] of Object.entries({smtpHost:'smtp.gmail.com',smtpPort:465,imapHost:'imap.gmail.com',imapPort:993}))form.elements[k].value=v;form.elements.smtpSecure.checked=true;form.elements.imapSecure.checked=true;};
form.addEventListener('submit',async e=>{e.preventDefault();const b={};for(const el of form.elements){if(!el.name)continue;b[el.name]=el.type==='checkbox'?el.checked:el.value;}try{await json('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});form.elements.password.value='';out.textContent='设置已保存；未发送邮件';load();}catch(err){out.textContent=err.message;}});
for(const kind of ['Smtp','Imap'])document.getElementById('test'+kind).onclick=async()=>{out.textContent='正在测试连接…';try{const d=await json('/api/settings/test/'+kind.toLowerCase(),{method:'POST'});out.textContent=d.message;}catch(e){out.textContent=e.message;}};
load();
