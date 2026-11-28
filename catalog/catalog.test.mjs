import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Readable} from 'node:stream';
import test from 'node:test';
import {gzipSync} from 'node:zlib';
import {compileCatalog,defaultModels,defaultEfforts,preferences,resolveRoute} from './catalog.mjs';
import {CatalogStore} from './store.mjs';
import {listenRoutes} from './serve.mjs';

const caps=defaultModels.map(slug=>({slug,default_reasoning_level:'medium',
  supported_reasoning_levels:[...defaultEfforts,'ultra'].map(effort=>({effort})),context_window:500000,input_modalities:['text','image']}));
const native={models:{'gemini-pro':{model:'MODEL_PLACEHOLDER_M400',displayName:'Native',remainingQuota:0.73}},
  groupedModels:{gemini:{displayName:'Native family',supportedThinkingLevels:[]}},
  agentModelSorts:[{displayName:'Recommended',groups:[{modelIds:['gemini-pro']}]},{displayName:'other',groups:[]}],defaultAgentModelId:'gemini-pro'};
function temp(t) {
  const dir=mkdtempSync(join(tmpdir(),'antigravity-native-models-'));
  t.after(()=>rmSync(dir,{recursive:true,force:true}));
  return dir;
}
test('preserve native rows, quota, default and groups; exact ten combinations; unsupported and empty selections',()=>{
  const original=structuredClone(native);
  const state=compileCatalog(native,caps);
  assert.equal(state.routes.size,10);
  assert.equal(new Set([...state.routes.values()].map(r=>r.slot)).size,10);
  assert.deepEqual(native,original);
  assert.deepEqual(state.catalog.models['gemini-pro'],original.models['gemini-pro']);
  assert.equal(state.catalog.defaultAgentModelId,'gemini-pro');
  assert.deepEqual(state.catalog.agentModelSorts[1],native.agentModelSorts[1]);
  for(const row of state.routes.values()){
    const entry=state.catalog.models[row.slug];
    assert.equal(entry.model,row.enum);
    assert.equal(entry.supportsThinking,true);
    assert.equal(entry.supportsImages,true);
    assert.equal(entry.supportedMimeTypes['application/pdf'],undefined);
    assert.equal(entry.supportedMimeTypes['image/png'],true);
    const route=resolveRoute(['models/'+row.slug,row.value],state);
    assert.deepEqual([route.model,route.effort],[row.model,row.effort]);
  }
  const settings=preferences();settings.efforts=['ultra','ULTRA','unknown'];
  const optional=compileCatalog(native,caps,settings,state.assignments);
  assert.equal(optional.catalog,native);
  assert.equal(optional.routes.size,0);
  assert.equal(optional.blocked.filter(row=>row.reason==='unsupported_effort').length,2);
  const empty=compileCatalog(native,caps,{...settings,efforts:[]},state.assignments);
  assert.equal(empty.catalog,native);
  assert.equal(empty.routes.size,0);
});
test('other models retain published native levels and exclude client modes',()=>{
  const raw=[{slug:'gpt-6.2-test',supported_reasoning_levels:['adaptive','max','minimal','none','ultra','low'].map(effort=>({effort}))}];
  const prefs={version:1,models:[raw[0].slug],efforts:['adaptive','ULTRA','minimal','none','low','max','absent']};
  const result=compileCatalog(native,raw,prefs);
  assert.deepEqual([...result.routes.values()].map(row=>row.effort),['none','minimal','low','max','adaptive']);
  assert.deepEqual(result.blocked,[{model:raw[0].slug,effort:'absent',reason:'unsupported_effort'}]);
});
test('model titles and effort order stay stable after toggling and with unordered provider capabilities',()=>{
  const scrambled=['high','max','low','medium','xhigh'];
  const unordered=caps.map(row=>({...row,supported_reasoning_levels:[...scrambled,'ultra'].map(effort=>({effort}))}));
  const previous=compileCatalog(native,caps);
  const state=compileCatalog(native,unordered,{...preferences(),efforts:[...scrambled,'Ultra']},previous.assignments);
  assert.deepEqual(state.assignments,previous.assignments);
  for(const [slug,title] of [['gpt-6.2-sol','GPT-6.2 Sol'],['gpt-6.2-astra','GPT-6.2 Astra']]){
    const group=state.catalog.groupedModels['codex-'+slug];
    assert.equal(group.displayName,title);
    assert.deepEqual(group.supportedThinkingLevels.map(level=>level.thinkingSuffix),defaultEfforts);
    assert.deepEqual(group.supportedThinkingLevels.map(level=>level.thinkingDisplayName),['Low','Medium','High','Extra High','Max']);
    assert.equal(group.defaultThinkingSuffix,'medium');
    for(const row of state.routes.values())if(row.model===slug){
      const level=group.supportedThinkingLevels.find(l=>l.thinkingSuffix===row.effort);
      assert.equal(state.catalog.models[row.slug].displayName,title+' ('+level.thinkingDisplayName+')');
      assert.deepEqual(resolveRoute([row.slug],state),{kind:'subscription',...row});
    }
  }
});
test('deterministic free slots, collision on refresh, bare enum and mixed identities fail closed',()=>{
  const first=compileCatalog(native,caps),row=[...first.routes.values()][0];
  const collision=structuredClone(native);
  collision.models.vendor={model:String(row.value),displayName:'another native'};
  const changed=compileCatalog(collision,caps,undefined,first.assignments);
  assert.equal(changed.catalog.models.vendor.model,String(row.value));
  assert.equal(changed.routes.has(row.slug),false);
  assert.equal(changed.blocked[0].reason,'native_owns_reserved_slot');
  assert.equal(resolveRoute([row.slug],changed).kind,'error');
  assert.equal(resolveRoute([row.value],changed).kind,'native');
  assert.equal(resolveRoute([row.value],first).kind,'error');
  assert.equal(resolveRoute([row.slug,'gemini-pro'],first).kind,'error');
  const other=compileCatalog(collision,caps);
  assert.notEqual(other.routes.get(row.slug).slot,row.slot);
  const sameName=structuredClone(native);sameName.models[row.slug]={model:'MODEL_PLACEHOLDER_M4'};
  assert.equal(resolveRoute([row.slug],compileCatalog(sameName,caps)).kind,'native');
  assert.equal(resolveRoute([row.slug],compileCatalog(sameName,caps,undefined,first.assignments)).kind,'error');
});
test('transactional storage distinguishes missing from intentionally empty, independent windows reject stale changes, and migrates legacy ag-codex slots',t=>{
  const file=join(temp(t),'test.sqlite');let db=new CatalogStore(file);
  // Seed a legacy v0.4.2 ag-codex-* assignment and verify slot preservation across migration.
  db.db.prepare('INSERT INTO catalog_assignments(slug,slot) VALUES(?,?)').run('ag-codex-11-gpt-6.2-sol-medium',777);
  const first=db.compile(native,caps);
  assert.equal(first.assignments['codex-gpt-6.2-sol-medium'],777);
  assert.equal(first.assignments['ag-codex-11-gpt-6.2-sol-medium'],undefined);
  assert.equal(resolveRoute(['ag-codex-11-gpt-6.2-sol-medium'],first).kind,'error');
  const sibling=new CatalogStore(file);
  try {
    const old=sibling.read();assert.deepEqual(old.settings.models,[...defaultModels]);
    db.update({...old.settings,models:[]},0);
    assert.throws(()=>sibling.update(old.settings,0),/another window/);
    db.close();db=new CatalogStore(file);
    assert.deepEqual(db.read().settings.models,[]);
    assert.equal(db.compile(native,caps).routes.size,0);
    db.update(old.settings,1);
    assert.deepEqual(db.compile(native,caps).assignments,first.assignments);
  }finally{db.close();sibling.close();}
});
const reply=(obj,statusCode=200)=>Object.assign(Readable.from([Buffer.from(JSON.stringify(obj))]),{statusCode,headers:{'content-type':'application/json'}});
async function transport(t,behavior,extraOptions={}) {
  const state={enabled:true,allowed:true,settings:preferences(),models:caps,catalog:structuredClone(native),gen:[],google:[],catalogCalls:[],events:[]};
  const dir=mkdtempSync(join(tmpdir(),'antigravity-native-router-'));
  const routes=await listenRoutes(dir,async request=>{
    if(request.path.includes('fetchAvailableModels')){
      state.catalogCalls.push({auth:request.headers.authorization,body:request.body?.toString('utf8')});
      if(state.onCatalog)return state.onCatalog(request);
      if(request.headers.authorization==='Bearer acct-b')return reply({error:'forbidden'},403);
      return reply(state.catalog);
    }
    state.google.push(request);
    return reply({native:true});
  },undefined,{getSettings:()=>state.settings,getModels:()=>state.models,enabled:()=>state.enabled,
    authorizeProbe:()=>state.allowed,record:(kind,meta)=>state.events.push({kind,...meta}),
    generate:args=>{state.gen.push(args);return behavior(args);},...extraOptions});
  t.after(()=>{routes.close();rmSync(dir,{recursive:true,force:true});});
  const call=(op,body,who='acct-a',headers={},signal)=>fetch(routes.urls.cloud+'/v1internal:'+op,{method:'POST',signal,
    headers:{'content-type':'application/json','authorization':'Bearer '+who,'x-goog-api-key':'fixture-only-google',...headers},body:JSON.stringify(body)});
  const catalog=async(project='scope-a',who='acct-a')=>(await call('fetchAvailableModels',{project},who)).json();
  const send=(model,project='scope-a',who='acct-a',signal)=>call('streamGenerateContent',{model,project,request:{contents:[{role:'user',parts:[{text:'bounded fixture'}]}],
    tools:[{functionDeclarations:[{name:'read_file',parameters:{type:'OBJECT'}}]}],test_private_key:'outer-only'}},who,{},signal);
  return {state,routes,catalog,send,call};
}
function* sample({model,effort}){yield {modelVersion:model,candidates:[{content:{parts:[{text:effort}]},finishReason:'STOP'}]};}
test('real loopback HTTP + Cloud Code SSE for 2x5, reject cross-account/project, stale selection and passthrough native',async t=>{
  const {state,catalog,send}=await transport(t,sample);
  const augmented=await catalog(),slugs=Object.keys(augmented.models).filter(k=>k.startsWith('codex-'));
  assert.equal(slugs.length,10);
  for(const id of slugs) {
    const reply=await send(id);
    assert.equal(reply.status,200);assert.match(reply.headers.get('content-type'),/event-stream/);
    const frame=JSON.parse((await reply.text()).trim().replace(/^data: /,''));
    const actual=state.gen.at(-1);
    assert.deepEqual(Object.keys(actual.payload),['contents','tools']);
    assert.equal(frame.response.modelVersion,actual.model);
    assert.equal(frame.response.candidates[0].content.parts[0].text,actual.effort);
    assert.equal(id,'codex-'+actual.model+'-'+actual.effort);
    assert.deepEqual(Object.keys(actual).sort(),['effort','model','payload','signal','stream']);
  }
  for(const [project,account] of [['scope-b','acct-a'],['scope-a','acct-b']])assert.equal((await send(slugs[0],project,account)).status,409);
  // Simulate 55-minute Google OAuth access-token rotation on the same bound project:
  // concurrent workers deduplicate into one fetchAvailableModels revalidation and all succeed (200).
  const beforeReval=state.catalogCalls.length;
  const rotated=await Promise.all([send(slugs[0],'scope-a','acct-a-rotated'),send(slugs[1],'scope-a','acct-a-rotated'),send(slugs[2],'scope-a','acct-a-rotated')]);
  assert.deepEqual(rotated.map(r=>r.status),[200,200,200]);
  await Promise.all(rotated.map(r=>r.text()));
  assert.equal(state.catalogCalls.length,beforeReval+1);
  assert.equal(state.catalogCalls.at(-1).auth,'Bearer acct-a-rotated');
  state.allowed=false;assert.equal((await send(slugs[0])).status,403);
  state.allowed=true;state.settings.efforts=[];assert.equal((await send(slugs[0])).status,409);
  state.settings=preferences();state.models=[];assert.equal((await send(slugs[0])).status,409);
  assert.equal(state.gen.length,13);assert.equal(state.google.length,0);
  const n=await send('gemini-pro');assert.deepEqual(await n.json(),{native:true});assert.equal(state.google.length,1);
  assert.equal(state.google[0].origin,'daily-cloudcode-pa.googleapis.com');
  assert.equal(state.events.filter(e=>e.kind==='native_generation').length,1);
  assert.ok(state.events.every(e=>!JSON.stringify(e).includes('Bearer')));
});
test('a stale revalidation cannot restore a binding revoked by a newer catalog poll', {timeout:5000}, async t=>{
  const {state,catalog,send,call}=await transport(t,sample);
  const slug=Object.keys((await catalog()).models).find(x=>x.startsWith('codex-'));
  const started=Promise.withResolvers(), release=Promise.withResolvers();
  let rotatedCalls=0;
  state.onCatalog=async req=>{
    assert.equal(req.headers.authorization,'Bearer acct-a-rotated');
    if(++rotatedCalls===1){
      started.resolve();
      await release.promise;
      return reply(state.catalog);
    }
    return reply({error:'forbidden'},403);
  };
  const stale=send(slug,'scope-a','acct-a-rotated');
  try {
    await started.promise;
    const poll=await call('fetchAvailableModels',{project:'scope-a'},'acct-a-rotated');
    assert.equal(poll.status,403);
    await poll.text();
  }finally{release.resolve();}
  const afterRevocation=await stale;
  assert.equal(afterRevocation.status,409);
  assert.equal((await afterRevocation.json()).error.message,'subscription_selection_unavailable');
  const subsequent=await send(slug,'scope-a','acct-a-rotated');
  assert.equal(subsequent.status,409);
  await subsequent.text();
  assert.equal(rotatedCalls,3);
  assert.equal(state.gen.length,0);
});

test('an empty project can bind a catalog but is not learned for token revalidation',async t=>{
  const {state,catalog,send}=await transport(t,sample);
  const slug=Object.keys((await catalog('')).models).find(x=>x.startsWith('codex-'));
  assert.ok(slug);
  const sameCredential=await send(slug,'');
  assert.equal(sameCredential.status,200);
  await sameCredential.text();
  const rotated=await send(slug,'','acct-a-rotated');
  assert.equal(rotated.status,409);
  await rotated.text();
  assert.equal(state.catalogCalls.length,1);
  assert.equal(state.gen.length,1);
});

test('upstream fails with explicit error; failure can recover without switching to native',async t=>{
  let down=true;
  const {state,catalog,send}=await transport(t,async function* (arg){
    if(down)throw Object.assign(Error('sensitive remote error omitted'),{status:503});
    yield* sample(arg);
  });
  const slug=Object.keys((await catalog()).models).find(x=>x.startsWith('codex-'));
  const fail=await send(slug);assert.equal(fail.status,503);
  assert.equal((await fail.json()).error.message,'subscription_backend_unavailable');
  down=false;const ok=await send(slug);assert.equal(ok.status,200);await ok.text();
  assert.equal(state.google.length,0);
});
test('native cancel and disabling a model in flight both abort subscription; zero Google requests',async t=>{
  const aborted=[];
  const {state,catalog,send}=await transport(t,async function* (arg) {
    yield* sample(arg);
    await new Promise(resolve=>arg.signal.addEventListener('abort',()=>{aborted.push(true);resolve();},{once:true}));
  });
  const slug=Object.keys((await catalog()).models).find(x=>x.startsWith('codex-'));
  const c=new AbortController(),partial=await send(slug,'scope-a','acct-a',c.signal);
  await partial.body.getReader().read();c.abort();
  const live=await send(slug);const reader=live.body.getReader();await reader.read();
  state.enabled=false;let tail='';
  while(true){const {done,value}=await reader.read();if(done)break;tail+=new TextDecoder().decode(value);}
  assert.match(tail,/subscription_selection_revoked/);assert.equal(aborted.length,2);assert.equal(state.google.length,0);
});
test('native passthrough passes target selector to stripPlanSignatures for Gemini vs Claude switching',async t=>{
  const seenSelectors=[],googleBodies=[];
  const dir=mkdtempSync(join(tmpdir(),'antigravity-native-sig-'));
  const routes=await listenRoutes(dir,async request=>{
    if(request.path.includes('fetchAvailableModels'))return reply(structuredClone(native));
    googleBodies.push(JSON.parse(request.body.toString('utf8')));
    return reply({native:true});
  },undefined,{getSettings:()=>preferences(),getModels:()=>caps,enabled:()=>true,authorizeProbe:()=>true,
    generate:sample,stripPlanSignatures:(contents,selector)=>{
      seenSelectors.push(selector);
      return contents.map(turn=>({...turn,parts:turn.parts.map(p=>p.thoughtSignature==='AGY_TEST'?
        (selector.startsWith('gemini-')?{...p,thoughtSignature:'skip_thought_signature_validator'}:{functionCall:p.functionCall}):p)}));
    }});
  t.after(()=>{routes.close();rmSync(dir,{recursive:true,force:true});});
  const call=(model)=>fetch(routes.urls.cloud+'/v1internal:streamGenerateContent',{method:'POST',
    headers:{'content-type':'application/json',authorization:'Bearer acct-a'},
    body:JSON.stringify({model,project:'scope-a',request:{contents:[{role:'model',parts:[{functionCall:{id:'c1',name:'read_file',args:{}},thoughtSignature:'AGY_TEST'}]}]}})});
  assert.equal((await call('gemini-3.8-flash-low')).status,200);
  assert.equal((await call('claude-sonnet-5-5-low')).status,200);
  assert.deepEqual(seenSelectors,['gemini-3.8-flash-low','claude-sonnet-5-5-low']);
  assert.equal(googleBodies[0].request.contents[0].parts[0].thoughtSignature,'skip_thought_signature_validator');
  assert.equal(googleBodies[1].request.contents[0].parts[0].thoughtSignature,undefined);
});

test('passes native Gemini requests above 32 MiB (raw and gzip) and returns explicit 413 on raw or decompressed overflow',async t=>{
  // 1. Default 256 MiB limit accepts a 34 MiB native Gemini payload (both raw and gzip-compressed).
  const {state,routes}=await transport(t,sample);
  const largeBlob='A'.repeat(34*1024*1024);
  const rawPayload=Buffer.from(JSON.stringify({model:'gemini-pro',project:'scope-a',
    request:{contents:[{role:'user',parts:[{inlineData:{mimeType:'audio/wav',data:largeBlob}}]}]}}));
  assert.ok(rawPayload.length>34*1024*1024);
  const rawRes=await fetch(routes.urls.cloud+'/v1internal:streamGenerateContent',{method:'POST',
    headers:{'content-type':'application/json',authorization:'Bearer acct-a'},body:rawPayload});
  assert.equal(rawRes.status,200);
  assert.deepEqual(await rawRes.json(),{native:true});
  const gzPayload=gzipSync(rawPayload,{level:1});
  assert.ok(gzPayload.length<2*1024*1024);
  const gzRes=await fetch(routes.urls.cloud+'/v1internal:streamGenerateContent',{method:'POST',
    headers:{'content-type':'application/json','content-encoding':'gzip',authorization:'Bearer acct-a'},body:gzPayload});
  assert.equal(gzRes.status,200);
  assert.deepEqual(await gzRes.json(),{native:true});
  assert.equal(state.google.length,2);

  // 2. Exceeding limit returns explicit 413 request_payload_too_large for both raw stream and gzip decompression.
  const bounded=await transport(t,sample,{maxBody:64*1024});
  const overRaw=Buffer.from(JSON.stringify({model:'gemini-pro',project:'scope-a',
    request:{contents:[{role:'user',parts:[{text:'B'.repeat(80*1024)}]}]}}));
  const r1=await fetch(bounded.routes.urls.cloud+'/v1internal:streamGenerateContent',{method:'POST',
    headers:{'content-type':'application/json',authorization:'Bearer acct-a'},body:overRaw});
  assert.equal(r1.status,413);
  assert.deepEqual(await r1.json(),{error:{code:413,message:'request_payload_too_large'}});
  const overGz=gzipSync(overRaw);
  assert.ok(overGz.length<4096);
  const r2=await fetch(bounded.routes.urls.cloud+'/v1internal:streamGenerateContent',{method:'POST',
    headers:{'content-type':'application/json','content-encoding':'gzip',authorization:'Bearer acct-a'},body:overGz});
  assert.equal(r2.status,413);
  assert.deepEqual(await r2.json(),{error:{code:413,message:'request_payload_too_large'}});
  assert.equal(bounded.state.events.filter(e=>e.kind==='request_error'&&e.status===413&&e.reason==='request_payload_too_large').length,2);
});

test('transient fetchAvailableModels 503 and network errors keep active GPT bindings while 401/403 revokes immediately',async t=>{
  let releaseStream;
  const {state,catalog,send,call}=await transport(t,async function* (arg){
    yield* sample(arg);
    await new Promise(resolve=>{
      releaseStream=resolve;
      arg.signal.addEventListener('abort',resolve,{once:true});
    });
  });
  const slug=Object.keys((await catalog()).models).find(x=>x.startsWith('codex-'));
  const live=await send(slug);
  const reader=live.body.getReader();
  const firstChunk=await reader.read();
  assert.equal(firstChunk.done,false);

  // 503 from Google fetchAvailableModels must NOT kill active GPT stream or clear binding.
  state.onCatalog=async()=>reply({error:'unavailable'},503);
  const poll503=await call('fetchAvailableModels',{project:'scope-a'});
  assert.equal(poll503.status,503);
  await poll503.text();
  // Network error from Google fetchAvailableModels must NOT kill active GPT stream or clear binding.
  state.onCatalog=async()=>{throw new Error('ECONNRESET');};
  const pollNet=await call('fetchAvailableModels',{project:'scope-a'});
  assert.equal(pollNet.status,502);
  await pollNet.text();
  await new Promise(r=>setTimeout(r,260));
  releaseStream();
  let rest='';
  while(true){const {done,value}=await reader.read();if(done)break;rest+=new TextDecoder().decode(value);}
  assert.doesNotMatch(rest,/subscription_selection_revoked/);

  // Another GPT request still succeeds using the preserved binding, then 401 revokes immediately.
  const live2=await send(slug);
  const reader2=live2.body.getReader();
  await reader2.read();
  state.onCatalog=async()=>reply({error:'unauthorized'},401);
  const poll401=await call('fetchAvailableModels',{project:'scope-a'});
  assert.equal(poll401.status,401);
  await poll401.text();
  let tail2='';
  while(true){const {done,value}=await reader2.read();if(done)break;tail2+=new TextDecoder().decode(value);}
  assert.match(tail2,/subscription_selection_revoked/);
  assert.equal((await send(slug)).status,409);
});
