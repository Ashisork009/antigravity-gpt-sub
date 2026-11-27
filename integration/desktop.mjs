import {readFileSync,writeFileSync,renameSync,mkdirSync,existsSync,unlinkSync} from 'node:fs';
import {join} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {listenRoutes} from '../catalog/serve.mjs';
import {preferences,modelTitle} from '../catalog/catalog.mjs';
import {openPlanGateway} from '../subscription/plan.mjs';
import {makeGenerate,stripPlanSignatures} from '../subscription/generate.mjs';
import {openGate} from './router/lease/gate.mjs';
import {electronVendor} from './vendor.mjs';

const read=(p,fallback)=>existsSync(p)?JSON.parse(readFileSync(p,'utf8')):fallback;
function publish(path,value){
  const tmp=path+'.'+randomUUID()+'.tmp';
  try{writeFileSync(tmp,JSON.stringify(value));renameSync(tmp,path);}
  finally{if(existsSync(tmp))unlinkSync(tmp);}
}
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');

export async function startDesktopRouter({stateDir,fetch,safeStorage,openExternal,fixture}){
  const run=join(stateDir,'run'), statusPath=join(run,'plan-panel.json'), request=join(run,'plan-login.request'), refreshReq=join(run,'plan-refresh.request');
  mkdirSync(run,{recursive:true});
  let rows=[], current=preferences(undefined),revision='', gate, listener, busy=false, refreshing=false, refreshTask=null, refreshQueued=false, retryAt=0,closing=false;
  let status={connected:false,authorizationPending:false}, catalogError=null, choicesError=null;
  const diag={mode:fixture?'fixture':'subscription',startedAt:new Date().toISOString(),seq:0,counts:{},recent:[]};
  const record=(kind,meta)=>{
    const safe={};
    for(const k of ['operation','listener','selector','selector_field','model','effort','status','cancelled','added','upstream_rows','route_count','tool_results','tool_calls','deltas','reason','mime','has_body','input_tokens','cached_tokens','output_tokens','reasoning_tokens','inst_hash','tools_hash','first_hash','cache_key','input_items','out_types'])
      if(['string','boolean','number'].includes(typeof meta[k]))safe[k]=meta[k];
    diag.counts[kind]=(diag.counts[kind]??0)+1;
    diag.recent.push({seq:++diag.seq,time:new Date().toISOString(),kind,...safe});
    if(diag.recent.length>180)diag.recent.shift();
    try{publish(join(run,'diagnostics.json'),diag);}catch{}
  };
  const plan=fixture ? await fixture(run) : openPlanGateway({stateDir,safeStorage,fetch,openExternal,record,onChange:()=>{retryAt=0;}});
  const display=()=>{
    const rev=hash({current,rows,live:status.connected,choicesError});
    const visible={connected:status.connected,pending:status.authorizationPending,refreshing:Boolean(refreshing),error:choicesError||catalogError||status.lastError||null,
      models:rows.map(r=>({id:r.slug,title:modelTitle(r.slug,r.display_name),efforts:(r.supported_reasoning_levels??[]).map(e=>e.effort)})),revision:rev,fixture:Boolean(fixture)};
    const text=JSON.stringify(visible);
    if(!existsSync(statusPath)||readFileSync(statusPath,'utf8')!==text)publish(statusPath,visible);
    if(rev!==revision){revision=rev;listener?.invalidate?.();}
  };
  function refreshModels(){
    if(refreshTask)return refreshTask;
    if(closing||!status.connected)return Promise.resolve();
    refreshing=true;
    display();
    refreshTask=(async()=>{
      try{
        rows=await plan.listModels({signal:AbortSignal.timeout(15000)});
        catalogError=null;retryAt=Date.now()+300000;
      }catch(e){
        const authRevoked=e?.status===401||e?.status===403||
          ['chatgpt_reauthorization_required','chatgpt_signin_required','chatgpt_plan_usage_not_granted'].includes(e?.code);
        if(authRevoked)rows=[];
        catalogError=e?.code||(e?.name==='TimeoutError'||e?.name==='AbortError'?'catalog_timeout':'catalog_unavailable');
        retryAt=Date.now()+15000;
      }finally{
        refreshing=false;refreshTask=null;
        if(!closing){
          status=await plan.status().catch(()=>status);
          if(!status.connected){rows=[];refreshQueued=false;retryAt=0;}
          else if(refreshQueued){refreshQueued=false;retryAt=0;}
          display();
        }
      }
    })();
    return refreshTask;
  }
  async function tick(){
    if(busy||closing)return;busy=true;
    try{
      try{current=preferences(read(join(stateDir,'model-preferences.json'),undefined));choicesError=null;}
      catch{current={version:1,models:[],efforts:[]};choicesError='invalid_preferences';}
      if(existsSync(request)){
        const cmd=read(request,{});unlinkSync(request);
        if(cmd.action==='signin'&&Date.now()-cmd.at>=0&&Date.now()-cmd.at<15000&&!fixture){
          try{await plan.signIn();}catch(e){catalogError=e.code||'signin_unavailable';}
        }
      }
      if(existsSync(refreshReq)){
        const cmd=read(refreshReq,{});unlinkSync(refreshReq);
        if(cmd.action==='refresh'&&Date.now()-cmd.at>=0&&Date.now()-cmd.at<15000&&!fixture){
          if(refreshing)refreshQueued=true;
          retryAt=0;
        }
      }
      status=await plan.status();
      if(!status.connected){rows=[];refreshQueued=false;retryAt=0;}
      else if(Date.now()>=retryAt&&!refreshing){refreshModels().catch(()=>{});}
      if(!closing)display();
    }finally{busy=false;}
  }
  await tick();
  if(status.connected&&!rows.length)await refreshModels();
  try{
    listener=await listenRoutes(run,electronVendor(fetch),undefined,{enabled:()=>gate?.enabled()??false,
      getSettings:()=>current,getModels:()=>rows,authorizeProbe:s=>gate?.authorizeProbe(s)??false,
      generate:makeGenerate(plan,record),stripPlanSignatures,record});
    gate=openGate(listener.urls);
  }catch(e){plan.close();listener?.close();throw e;}
  const timer=setInterval(()=>tick().catch(()=>{}),450);timer.unref?.();
  return {cloud:listener.urls.cloud,close(){closing=true;clearInterval(timer);gate.close();listener.close();plan.close();}};
}
