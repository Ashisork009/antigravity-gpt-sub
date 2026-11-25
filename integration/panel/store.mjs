import {createHash,randomUUID} from 'node:crypto';
import {createServer} from 'node:net';
import {existsSync,mkdirSync,readFileSync,realpathSync,renameSync,unlinkSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';

export const defaultModels=['gpt-6.2-sol','gpt-6.2-astra'];
export const defaultEfforts=['low','medium','high','xhigh','max'];
const models=/^[a-z0-9][a-z0-9._-]{0,119}$/;
const efforts=/^[a-z0-9][a-z0-9_-]{0,29}$/;
// Older releases permitted this Codex orchestrator mode in saved UI preferences.
const nativeEfforts=list=>Array.isArray(list)?list.filter(e=>typeof e!=='string'||e.trim().toLowerCase()!=='ultra'):list;
function valid(list,pattern) {
  return Array.isArray(list)&&list.length<=256&&list.every(x=>typeof x==='string'&&pattern.test(x))&&new Set(list).size===list.length;
}
function error(message,status=400){return Object.assign(Error(message),{status});}
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
function direct(path){if(existsSync(path)&&realpathSync.native(path).toLowerCase()!==resolve(path).toLowerCase())throw error('storage_path_changed',409);return path;}
function publish(path,data) {
  direct(path);
  const tmp=path+'.'+randomUUID()+'.tmp';
  try{writeFileSync(tmp,JSON.stringify(data),{flag:'wx',mode:0o600});renameSync(tmp,path);}
  finally{if(existsSync(tmp))unlinkSync(tmp);}
}
export function panelStore(dir) {
  const root=resolve(dir),run=join(root,'run'),cfg=join(root,'model-preferences.json');
  const mutex='\\\\.\\pipe\\antigravity-model-preferences-'+digest(root.toLowerCase()).slice(0,28);
  function snapshot(){
    direct(root);direct(run);direct(cfg);
    const raw=existsSync(cfg)?readFileSync(cfg):null;
    const prefs=raw?JSON.parse(raw):{version:1,models:[...defaultModels],efforts:[...defaultEfforts]};
    prefs.efforts=nativeEfforts(prefs.efforts);
    if(prefs.version!==1||!valid(prefs.models,models)||!valid(prefs.efforts,efforts))throw error('invalid_existing_preferences',409);
    const status=join(run,'plan-panel.json');
    const meta=existsSync(status)?JSON.parse(readFileSync(direct(status))):{error:'gateway_starting'};
    const rows=(Array.isArray(meta.models)?meta.models:[]).filter(r=>typeof r?.id==='string'&&models.test(r.id))
      .map(r=>({id:r.id,title:typeof r.title==='string'?r.title:r.id,efforts:nativeEfforts(r.efforts)})).filter(r=>valid(r.efforts,efforts));
    return {prefs,stamp:raw?digest(raw):'default',connected:meta.connected===true,pending:meta.pending===true,fixture:meta.fixture===true,
      error:typeof meta.error==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(meta.error)?meta.error:null,models:rows,
      revision:typeof meta.revision==='string'?meta.revision:''};
  }
  async function save(data){
    const lock=createServer(socket=>socket.destroy());
    try{
      await new Promise((ok,no)=>{lock.once('error',no);lock.listen(mutex,ok);});
    }catch{throw error('settings_changed',409);}
    try{
      const before=snapshot();
      if(before.stamp!==data?.stamp)throw error('settings_changed',409);
      const selected=data.prefs;
      if(selected?.version!==1||!valid(selected.models,models)||!valid(selected.efforts,efforts))throw error('invalid_preferences');
      const allowedModels=new Set([...before.models.map(r=>r.id),...before.prefs.models,...defaultModels]);
      const allowedEfforts=new Set([...before.models.flatMap(r=>r.efforts),...before.prefs.efforts,...defaultEfforts]);
      if(selected.models.some(x=>!allowedModels.has(x))||selected.efforts.some(x=>!allowedEfforts.has(x)))throw error('catalog_changed',409);
      mkdirSync(root,{recursive:true});
      publish(cfg,{version:1,models:selected.models,efforts:selected.efforts});
      return snapshot();
    }finally{await new Promise(ok=>lock.close(ok));}
  }
  function signin() {
    const state=snapshot();
    if(state.fixture)throw error('fixture_mode',409);
    if(state.pending)return {queued:true};
    mkdirSync(run,{recursive:true});
    const path=join(run,'plan-login.request');direct(path);
    publish(path,{action:'signin',at:Date.now()});return {queued:true};
  }
  return {snapshot,save,signin};
}

