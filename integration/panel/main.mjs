import {readFileSync} from 'node:fs';
import {homedir} from 'node:os';
import {join} from 'node:path';
import {connect} from 'node:net';
import {SidecarApp,Response} from 'sidecar_sdk';
import {panelStore} from './store.mjs';
import {skillStore} from './skill-store.mjs';

if(!process.env.ANTIGRAVITY_SIDECAR_UI_TOKEN) throw Error('This settings view requires a host-authenticated panel');
const stateDir=join(homedir(),'.antigravity-native-model-router');
const app=new SidecarApp(),store=panelStore(stateDir),skills=skillStore(stateDir);
function safeSkillSnapshot(){
  try{return skills.snapshot();}catch{return {error:'skill_unavailable'};}
}
const safeHeaders={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
  'Content-Security-Policy':"default-src 'self'; script-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"};
for(const [route,file,mime] of [['/','index.html','text/html; charset=utf-8'],['/panel.js','panel.js','application/javascript'],['/panel.css','panel.css','text/css']]) {
  const content=readFileSync(new URL(file,import.meta.url),'utf8');
  app.page(route,()=>new Response(content,{contentType:mime,headers:safeHeaders}));
}
function endpoint(path,handler) {
  app.api(path,async data=>{
    try{return new Response(JSON.stringify(await handler(data)),{contentType:'application/json',headers:safeHeaders});}
    catch(e){return new Response(JSON.stringify({error:e.status?e.message:'settings_unavailable'}),
      {contentType:'application/json',status:e.status??503,headers:safeHeaders});}
  },'POST');
}
endpoint('/api/state',()=>({...store.snapshot(),skill:safeSkillSnapshot()}));
endpoint('/api/model-preferences',async data=>({...await store.save(data),skill:safeSkillSnapshot()}));
endpoint('/api/signin',store.signin);
endpoint('/api/skill',async data=>{
  const nextSkill=await skills.update(data);
  return {...store.snapshot(),skill:nextSkill};
});
process.chdir(homedir());
await app.run();
const owner=new URL('http://'+process.env.ANTIGRAVITY_LS_ADDRESS);
if(!['127.0.0.1','localhost','[::1]'].includes(owner.hostname)||!owner.port)throw Error('Missing native host address');
let missed=0,closing=false,checking=false;
const tick=setInterval(()=>{
  if(checking||closing)return;checking=true;
  const socket=connect(Number(owner.port),owner.hostname.replace(/^\[|\]$/g,''));
  socket.setTimeout(1300);
  socket.once('connect',()=>{missed=0;socket.end();});
  socket.once('timeout',()=>socket.destroy(Error('host timeout')));
  socket.once('error',()=>{if(++missed>=3)void stop();});
  socket.once('close',()=>{checking=false;});
},2000);
async function stop(){
  if(closing)return;closing=true;clearInterval(tick);await app.close();
}
process.once('SIGTERM',stop);process.once('SIGINT',stop);

