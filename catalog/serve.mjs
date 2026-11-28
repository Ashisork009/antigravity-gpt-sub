import {createHmac,randomBytes} from 'node:crypto';
import {createServer} from 'node:http';
import {join} from 'node:path';
import {once} from 'node:events';
import {pipeline} from 'node:stream/promises';
import {resolveRoute,modelCapabilities,preferences} from './catalog.mjs';
import {CatalogStore} from './store.mjs';
import {collect,readJson,forGoogle,callGoogle,error,cloudHost,apiHost,maxBody} from './transport.mjs';

const legacy=new Set(['local-codex-subscription','native-model-probe']);
const headerNames=['content-type','content-encoding','retry-after','cache-control','www-authenticate'];
const wireFields=['contents','tools','toolConfig','generationConfig','systemInstruction','safetySettings',
  'tool_config','generation_config','system_instruction','safety_settings'];
const safeReasons=new Set(['subscription_selection_unavailable','conflicting_selectors','expected_native_model_slug',
  'ambiguous_model_identity','unbound_subscription_selection','subscription_backend_unavailable','invalid_model_request',
  'request_payload_too_large','subscription_selection_revoked','subscription_rate_limited','unsupported_reasoning_effort',
  'subscription_not_authenticated','subscription_rejected','model_inference_failed','legacy_model_unavailable','only_native_language_service']);
const fail=(status,reason)=>Object.assign(error(status,reason),{reason});
const safeId=id=>typeof id==='string'&&/^[\w.-]{1,190}$/.test(id)?id:null;
function errorReason(cause) {
  if(safeReasons.has(cause?.reason))return cause.reason;
  if(typeof cause?.code==='string'&&/^(?:chatgpt_plan_|chatgpt_|subscription_)[a-z0-9_]{1,72}$/.test(cause.code))return cause.code;
}
function endError(res,cause) {
  if(res.destroyed||res.writableEnded)return;
  const status=Number(cause?.status??cause?.statusCode);
  const code=Number.isInteger(status)&&status>=400&&status<=599?status:502;
  const fallback=code===413?'request_payload_too_large':code===429?'subscription_rate_limited':[401,403].includes(code)?'subscription_not_authenticated':
    code===400||code===422?'subscription_rejected':code===503?'subscription_backend_unavailable':'model_inference_failed';
  const message=errorReason(cause)??fallback;
  const data=JSON.stringify({error:{code,message}});
  if(res.headersSent)res.end('data: '+data+'\n\n');
  else {res.writeHead(code,{'content-type':'application/json','cache-control':'no-store'});res.end(data);}
}
function routeFor(path,listener) {
  const internal=/^\/v1internal:(fetchAvailableModels|generateContent|streamGenerateContent)$/.exec(path);
  const api=/^\/(?:v1|v1beta)\/models\/([\w.-]+):(generateContent|streamGenerateContent)$/.exec(path);
  const operation=internal?.[1]??api?.[2]??'other';
  const cloud=path.startsWith('/v1internal:')||path.startsWith('/v1internal/');
  return {origin:cloud||(!api&&listener==='cloud')?cloudHost:apiHost,cloud,model:api?.[1],operation,
    catalog:operation==='fetchAvailableModels',gen:operation.endsWith('enerateContent'),stream:operation==='streamGenerateContent'};
}
function settingsFrom(options) {
  const raw=options.getSettings();
  return preferences(raw?.settings??raw);
}
function isSelected(options,row) {
  if(!options.enabled())return false;
  const settings=settingsFrom(options);
  if(!settings.models.includes(row.model)||!settings.efforts.includes(row.effort))return false;
  return modelCapabilities(options.getModels()).get(row.model)?.efforts.includes(row.effort)??false;
}
function requestedPorts(previous) {
  const ports={};
  if(previous){
    for(const k of ['cloud','api','inference']){
      const u=new URL(previous[k]);
      if(u.protocol!=='http:'||u.hostname!=='127.0.0.1'||!u.port||previous[k]!==u.origin)throw Error('Invalid previous endpoint');
      ports[k]=Number(u.port);
    }
    if(new Set(Object.values(ports)).size!==3)throw Error('Duplicate listener');
  }
  return ports;
}
async function dispatch(options,route,body,row,res,signal) {
  if(!body||!Array.isArray(body.contents))throw fail(400,'invalid_model_request');
  // The outer envelope, including its Google project, and all vendor credentials stop here.
  const payload=Object.fromEntries(wireFields.filter(k=>Object.hasOwn(body,k)).map(k=>[k,body[k]]));
  const frames=await options.generate({payload,stream:route.stream,signal,model:row.model,effort:row.effort});
  let count=0,one;
  for await(const frame of frames) {
    signal.throwIfAborted();
    if(!frame||typeof frame!=='object'||frame.error)throw fail(502,'model_inference_failed');
    count++;
    const data=route.cloud?{response:frame,metadata:{}}:frame;
    if(route.stream) {
      if(!res.headersSent)res.writeHead(200,{'content-type':'text/event-stream','cache-control':'no-store'});
      if(!res.write('data: '+JSON.stringify(data)+'\n\n'))await once(res,'drain',{signal});
    }else{
      if(count!==1)throw fail(502,'model_inference_failed');
      one=data;
    }
  }
  if(!count)throw fail(502,'model_inference_failed');
  if(!route.stream)res.writeHead(200,{'content-type':'application/json','cache-control':'no-store'});
  res.end(route.stream?undefined:JSON.stringify(one));
}

export async function listenRoutes(runDir,vendor=callGoogle,previous,options={}) {
  for(const k of ['enabled','authorizeProbe','getSettings','getModels','generate']){
    if(typeof options[k]!=='function')throw Error('Missing model router callback '+k);
  }
  const ports=requestedPorts(previous);
  const bodyLimit=Number.isSafeInteger(options.maxBody)&&options.maxBody>0?options.maxBody:maxBody;
  const store=options.store??new CatalogStore(join(runDir,'native-model-catalog.sqlite'));
  const record=options.record??(()=>{});
  const key=randomBytes(32),bindings=new Map(),active=new Set(),servers=[],urls={};
  let reserved=store.assignments(),sequence=0;
  const pendingCatalogs=new Map(),knownProjects=new Set(),revalidating=new Map();
  function current(scope) {
    const entry=bindings.get(scope);
    return entry&&entry.until>Date.now()?entry.state:undefined;
  }
  function bindScope(scope,project,state) {
    bindings.delete(scope);
    if(state){
      if(bindings.size>=200)bindings.delete(bindings.keys().next().value);
      bindings.set(scope,{state,until:Date.now()+1800000});
      if(project&&state.routes.size)knownProjects.add(project);
    }
  }
  // When Antigravity rotates its short-lived Google OAuth access token (~55m) before the next
  // scheduled fetchAvailableModels poll, revalidate the refreshed token once with Google so active
  // multi-agent workers do not suffer a 409 blackout, while keeping invalid/foreign tokens fail-closed.
  async function revalidateScope(scope,project,reqHeaders,meta) {
    const inflight=revalidating.get(scope);
    if(inflight)return inflight;
    const task=(async()=>{
      const order=++sequence;
      pendingCatalogs.set(scope,order);
      const body=Buffer.from(JSON.stringify(project?{project}:{}));
      const outgoing=forGoogle(reqHeaders,true);
      delete outgoing['content-encoding'];
      outgoing['content-type']='application/json';
      outgoing['content-length']=String(body.length);
      let status=502;
      try {
        const up=await vendor({origin:cloudHost,path:'/v1internal:fetchAvailableModels',method:'POST',
          headers:outgoing,signal:AbortSignal.timeout(15000),body});
        status=up.statusCode;
        const raw=await collect(up);
        if(pendingCatalogs.get(scope)!==order) return current(scope);
        if(status!==200) {
          record('catalog_revalidated',{...meta,status,route_count:0});
          return undefined;
        }
        const catalog=readJson(raw,up.headers['content-encoding']);
        const whole=catalog&&!catalog.nextPageToken&&!catalog.next_page_token;
        if(!whole) {
          record('catalog_revalidated',{...meta,status,route_count:0});
          return undefined;
        }
        const compiled=store.compile(catalog,options.getModels(),options.enabled(),settingsFrom(options));
        reserved=compiled.assignments;
        bindScope(scope,project,compiled);
        record('catalog_revalidated',{...meta,status:200,route_count:compiled.routes.size});
        return compiled;
      } catch {
        record('catalog_revalidated',{...meta,status,route_count:0});
        return undefined;
      } finally {
        if(pendingCatalogs.get(scope)===order)pendingCatalogs.delete(scope);
      }
    })();
    revalidating.set(scope,task);
    try {return await task;}
    finally {if(revalidating.get(scope)===task)revalidating.delete(scope);}
  }
  function invalidate() {
    for(const item of active) {
      if(item.signal.aborted)continue;
      let keep=false;
      try {
        const latest=bindings.get(item.scope)?.state.routes.get(item.row.slug);
        keep=latest?.slot===item.row.slot&&isSelected(options,item.row);
      }catch { /* Revocation also applies when the control plane is unavailable. */ }
      if(!keep){
        const reason=fail(409,'subscription_selection_revoked');
        item.abort.abort(reason);endError(item.res,reason);
      }
    }
  }
  const timer=setInterval(()=>{if(active.size)invalidate();},200);timer.unref();
  async function handle(listener,server,req,res) {
    const abort=new AbortController(),{signal}=abort;
    res.once('close',()=>{if(!res.writableFinished)abort.abort();});
    let meta={listener,operation:'other'},local=false,scope,order;
    try {
      if(req.headers.host!=='127.0.0.1:'+server.address().port||req.headers.origin||req.headers['sec-fetch-site']==='cross-site')throw fail(403,'only_native_language_service');
      if(!/^\/(?!\/)/.test(req.url)||/[\\#\x00-\x1f]/.test(req.url)||!['GET','POST','HEAD','PUT','PATCH','DELETE'].includes(req.method))throw fail(400,'invalid_model_request');
      const route=routeFor(req.url.split('?')[0],listener);
      meta={listener,operation:route.operation};
      const inspect=(route.catalog||route.gen)&&req.method==='POST';
      let bytes=inspect?await collect(req,bodyLimit):undefined,rebuilt=false;
      const parsed=bytes&&readJson(bytes,req.headers['content-encoding'],bodyLimit);
      const credential=req.headers.authorization??req.headers['x-goog-api-key'];
      const project=typeof parsed?.project==='string'?parsed.project:'';
      scope=credential?createHmac('sha256',key).update(JSON.stringify([credential,project])).digest('hex'):'';
      if(route.gen){
        if(req.method!=='POST'||!parsed)throw fail(400,'invalid_model_request');
        const fields=['model','modelId','model_id'].filter(k=>Object.hasOwn(parsed,k));
        const selectors=[...(route.model?[route.model]:[]),...fields.map(k=>parsed[k])];
        if(!selectors.length)throw fail(400,'invalid_model_request');
        meta={...meta,selector:safeId(String(selectors[0])),selector_field:route.model?'path':fields[0]};
        if(selectors.some(v=>legacy.has(String(v).replace(/^models\//,''))))throw fail(409,'legacy_model_unavailable');
        let state=current(scope);
        let plan=resolveRoute(selectors,state??{routes:new Map(),assignments:reserved,occupied:new Set(),conflictingSlugs:new Set(),nativeSlugs:new Set()});
        if(!state&&route.cloud&&scope&&knownProjects.has(project)&&plan.kind==='error'&&plan.reason==='subscription_selection_unavailable'&&options.enabled()) {
          if(!await options.authorizeProbe(req.socket))throw fail(403,'only_native_language_service');
          state=await revalidateScope(scope,project,req.headers,meta);
          if(state)plan=resolveRoute(selectors,state);
        }
        if(plan.kind==='error')throw fail(plan.status,plan.reason);
        if(plan.kind==='subscription') {
          local=true;
          if(!scope||!state||!isSelected(options,plan))throw fail(409,'subscription_selection_unavailable');
          if(!await options.authorizeProbe(req.socket))throw fail(403,'only_native_language_service');
          if(current(scope)?.routes.get(plan.slug)?.slot!==plan.slot||!isSelected(options,plan))throw fail(409,'subscription_selection_unavailable');
          meta={...meta,model:plan.model,effort:plan.effort};
          const item={scope,row:plan,res,abort,signal};active.add(item);
          try {
            record('model_generation',meta);
            await dispatch(options,route,route.cloud?parsed.request:parsed,plan,res,signal);
            record('model_complete',meta);
          }finally{active.delete(item);}
          return;
        }
        if(typeof options.stripPlanSignatures==='function') {
          const envelope=route.cloud?parsed.request:parsed;
          const contents=options.stripPlanSignatures(envelope?.contents,String(selectors[0]??''));
          if(envelope&&contents!==envelope.contents) {
            const clean={...envelope,contents};
            bytes=Buffer.from(JSON.stringify(route.cloud?{...parsed,request:clean}:clean));rebuilt=true;
          }
        }
        record('native_generation',meta);
      }
      if(route.catalog&&scope){
        order=++sequence;pendingCatalogs.set(scope,order);
      }
      const outgoing=forGoogle(req.headers,route.catalog);
      if(rebuilt){delete outgoing['content-encoding'];outgoing['content-length']=String(bytes.length);}
      const up=await vendor({origin:route.origin,path:req.url,method:req.method,headers:outgoing,signal,
        body:bytes??(['GET','HEAD'].includes(req.method)?undefined:req)});
      const headers=Object.fromEntries(headerNames.filter(k=>up.headers[k]).map(k=>[k,up.headers[k]]));
      if(route.catalog&&up.statusCode===200){
        const raw=await collect(up),catalog=readJson(raw,headers['content-encoding']);
        let state,added=0,catalogError;
        const newest=scope&&pendingCatalogs.get(scope)===order;
        const whole=catalog&&!catalog.nextPageToken&&!catalog.next_page_token&&!new URL(req.url,'http://localhost').searchParams.has('pageToken');
        if(newest&&whole){
          try{
            state=store.compile(catalog,options.getModels(),options.enabled(),settingsFrom(options));
            reserved=state.assignments;
          }catch{catalogError='subscription_catalog_unavailable';}
        }
        if(newest){
          bindScope(scope,project,state);
          if(state)added=state.routes.size;
          invalidate();
        }
        record('catalog',{...meta,status:200,upstream_rows:Object.keys(catalog?.models??{}).length,added:Boolean(added),
          route_count:added,enabled:options.enabled(),identity_collision:state?.blocked.some(r=>r.reason.includes('collision'))??false,
          slot_occupied:state?.blocked.some(r=>r.reason==='native_owns_reserved_slot')??false,
          recommended_first_group_contains_probe:Boolean(added),...(catalogError?{reason:catalogError}:{})});
        if(added)delete headers['content-encoding'];
        res.writeHead(200,headers);res.end(added?JSON.stringify(state.catalog):raw);return;
      }
      if(route.catalog&&scope&&pendingCatalogs.get(scope)===order&&(up.statusCode===401||up.statusCode===403)){bindings.delete(scope);invalidate();}
      res.writeHead(up.statusCode,headers);await pipeline(up,res);
    }catch(err){
      if(order!==undefined&&pendingCatalogs.get(scope)===order&&(err?.status===401||err?.status===403)){bindings.delete(scope);invalidate();}
      const cause=signal.reason?.reason?signal.reason:err;
      record(local?'model_error':'request_error',{...meta,status:cause.status??502,cancelled:signal.aborted,
        ...(errorReason(cause)?{reason:errorReason(cause)}:{})});
      endError(res,cause);
    }finally{
      if(order!==undefined&&pendingCatalogs.get(scope)===order)pendingCatalogs.delete(scope);
    }
  }
  let closed=false;
  function close(){
    if(closed)return;
    closed=true;clearInterval(timer);
    for(const entry of active)entry.abort.abort();
    for(const server of servers){server.close();server.closeAllConnections();}
    if(!options.store)store.close();
  }
  try{
    for(const listener of ['cloud','api','inference']){
      const server=createServer((req,res)=>handle(listener,server,req,res));servers.push(server);
      await new Promise((ok,fail)=>{server.once('error',fail);server.listen(ports[listener]??0,'127.0.0.1',ok);});
      urls[listener]='http://127.0.0.1:'+server.address().port;
    }
    return {urls,close,invalidate};
  }catch(err){close();throw err;}
}
