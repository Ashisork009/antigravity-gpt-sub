import assert from 'node:assert/strict';
import {createCipheriv,createDecipheriv,generateKeyPairSync,sign,randomBytes,createHash} from 'node:crypto';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import test from 'node:test';
import {openPlanGateway,planRequest,projectModels} from './plan.mjs';

const pair=generateKeyPairSync('rsa',{modulusLength:2048});
const jwk={...pair.publicKey.export({format:'jwk'}),alg:'RS256',use:'sig',kid:'fixture'};
const base64url=obj=>Buffer.from(JSON.stringify(obj)).toString('base64url');
const rights='openid offline_access resource.invoke chatgpt.tokens.use.direct';
const client='oaiapp_test_client',issuer='https://auth.openai.com';
function credentialStore() {
  const key=randomBytes(32);
  return {
    isEncryptionAvailable:()=>true,
    encryptString(s) {
      const iv=randomBytes(12),cipher=createCipheriv('aes-256-gcm',key,iv);
      const body=Buffer.concat([cipher.update(s,'utf8'),cipher.final()]);
      return Buffer.concat([iv,cipher.getAuthTag(),body]);
    },
    decryptString(b) {
      const cipher=createDecipheriv('aes-256-gcm',key,b.subarray(0,12));
      cipher.setAuthTag(b.subarray(12,28));
      return Buffer.concat([cipher.update(b.subarray(28)),cipher.final()]).toString();
    }
  };
}
const reply=(payload,status=200)=>new Response(JSON.stringify(payload),{status});
async function setup(t,{omitScope=false,badNonce=false,invalidRefreshGrant=false}={}) {
  const stateDir=await mkdtemp(join(tmpdir(),'plan-test-'));
  t.after(()=>rm(stateDir,{recursive:true,force:true}));
  const safeStorage=credentialStore();
  const events=[];
  let url,force401=false;
  const hooks={stateDir,safeStorage,openExternal:async raw=>{url=new URL(raw);},fetch:async(raw,opts)=>{
    assert.equal(opts.redirect,'error');assert.equal(opts.credentials,'omit');
    if(raw===issuer+'/.well-known/jwks.json') return reply({keys:[jwk]});
    if(raw===issuer+'/api/accounts/oauth/token') {
      const form=new URLSearchParams(opts.body);
      assert.equal(form.get('client_id'),client);
      assert.equal(form.get('resource'),'https://api.openai.com/v1');
      if(form.get('grant_type')==='refresh_token') {
        assert.equal(form.get('refresh_token'),'fixture-refresh');
        assert.equal(form.has('scope'),false);
        events.push('refresh');await delay(10);
        if(invalidRefreshGrant)return reply({error:'invalid_grant'},400);
        return reply({access_token:'fixture-access-2',refresh_token:'next-refresh',expires_in:3600,token_type:'bearer'});
      }
      assert.equal(form.get('redirect_uri'),url.searchParams.get('redirect_uri'));
      assert.equal(createHash('sha256').update(form.get('code_verifier')).digest('base64url'),url.searchParams.get('code_challenge'));
      const now=Math.floor(Date.now()/1000);
      const claims={iss:issuer,aud:client,nonce:badNonce?'other':url.searchParams.get('nonce'),
        sub:'synthetic-subject',iat:now,exp:now+3600};
      const input=base64url({kid:'fixture',alg:'RS256'})+'.'+base64url(claims);
      return reply({id_token:input+'.'+sign('RSA-SHA256',Buffer.from(input),pair.privateKey).toString('base64url'),
        token_type:'bearer',scope:omitScope?'openid':rights,expires_in:3600,refresh_token:'fixture-refresh',access_token:'fixture-access'});
    }
    assert.match(raw,/^https:\/\/api\.openai\.com\/v1\/(responses|models)$/);
    const sentBody=opts.body?JSON.parse(opts.body):null;
    const expectedHeaders=opts.body?(sentBody.prompt_cache_key?['accept','authorization','content-type','session-id']:['accept','authorization','content-type']):['accept','authorization'];
    assert.deepEqual(Object.keys(opts.headers).sort(),expectedHeaders);
    if (sentBody?.prompt_cache_key) assert.equal(opts.headers['session-id'],sentBody.prompt_cache_key);
    if(force401&&opts.headers.authorization==='Bearer fixture-access') return reply({},401);
    if(raw.endsWith('/models'))return reply({models:[{slug:'gpt-a',display_name:'A',visibility:'list',
      default_reasoning_level:'medium',supported_reasoning_levels:[{effort:'medium',description:'M'}]}]});
    const body=JSON.parse(opts.body);events.push({body,signal:opts.signal});
    return new Response('data: {"type":"response.completed"}\n\n',{headers:{'content-type':'text/event-stream'}});
  }};
  const gateway=openPlanGateway(hooks);t.after(()=>gateway.close());
  async function callback(stateOverride) {
    const u=new URL(url.searchParams.get('redirect_uri'));
    u.search=new URLSearchParams({code:'synthetic-code',state:stateOverride??url.searchParams.get('state'),client_id:client}).toString();
    return (await fetch(u)).status;
  }
  return {stateDir,gateway,getURL:()=>url,callback,hooks,events,expire(){force401=true;}};
}

test('official login flow, protected local grant, idempotent refresh and forwarding',async t=>{
  const f=await setup(t);
  await assert.rejects(f.gateway.listModels(),{code:'chatgpt_signin_required'});
  assert.deepEqual(await f.gateway.signIn(),{pending:true});
  assert.equal(f.getURL().origin,issuer);
  assert.equal(f.getURL().searchParams.get('client_id'),'dynamic_agent_client');
  assert.equal(f.getURL().searchParams.get('scope'),rights.replace('openid offline_access','openid profile email offline_access'));
  assert.match(f.getURL().searchParams.get('ext_agent_host_id'),/^urn:uuid:/);
  assert.equal(await f.callback('wrong'),400);
  assert.equal(await f.callback(),200);
  assert.equal((await f.gateway.status()).connected,true);
  const encrypted=await readFile(join(f.stateDir,'subscription','connection.dpapi'));
  assert.equal(encrypted.includes(Buffer.from('fixture-access')),false);
  f.expire();
  const second=openPlanGateway(f.hooks);t.after(()=>second.close());
  await Promise.all([second.listModels(),f.gateway.listModels(),second.listModels()]);
  assert.equal(f.events.filter(e=>e==='refresh').length,1);
  const controller=new AbortController();
  const body={model:'gpt-a',reasoning:{effort:'high'},prompt_cache_key:'agy-0123456789abcdef',input:[{type:'function_call',name:'read',arguments:'{}',call_id:'prior'},
    {type:'function_call_output',call_id:'prior',output:'fixture'}],tools:[{type:'function',name:'read',parameters:{type:'object'}}],
    max_output_tokens:10,temperature:0,store:true,metadata:{test:true}};
  const res=await f.gateway.respond({body,signal:controller.signal});assert.match(await res.text(),/response.completed/);
  const sent=f.events.at(-1);assert.equal(sent.body.model,'gpt-a');assert.equal(sent.body.reasoning.effort,'high');
  assert.equal(sent.body.tools[0].type,'namespace');assert.equal(sent.body.input[0].namespace,'antigravity');
  assert.equal(sent.body.input[1].call_id,'prior');assert.equal(sent.body.max_output_tokens,undefined);
  assert.equal(sent.body.store,false);assert.equal(sent.body.stream,true);
  controller.abort();assert.ok(sent.signal.aborted);
});
test('invalid_grant on token refresh marks the gateway disconnected until reauthorization',async t=>{
  const f=await setup(t,{invalidRefreshGrant:true});
  await f.gateway.signIn();
  assert.equal(await f.callback(),200);
  assert.equal((await f.gateway.status()).connected,true);
  f.expire();
  await assert.rejects(f.gateway.listModels(),{status:400,code:'chatgpt_reauthorization_required'});
  assert.equal(f.events.filter(e=>e==='refresh').length,1);
  assert.deepEqual(await f.gateway.status(),{
    connected:false,authorizationPending:false,lastError:'chatgpt_reauthorization_required',
  });
  await f.gateway.signIn();
  assert.equal(await f.callback(),200);
  assert.deepEqual(await f.gateway.status(),{connected:true,authorizationPending:false,lastError:undefined});
});

test('missing direct plan scope cannot initialize inference',async t=>{
  const f=await setup(t,{omitScope:true});await f.gateway.signIn();
  assert.equal(await f.callback(),400);assert.equal((await f.gateway.status()).connected,false);
  assert.equal((await f.gateway.status()).lastError,'chatgpt_plan_usage_not_granted');
});
test('incorrect ID-token nonce cannot replace a subscription grant',async t=>{
  const f=await setup(t,{badNonce:true});await f.gateway.signIn();
  assert.equal(await f.callback(),400);assert.equal((await f.gateway.status()).connected,false);
});
test('accepts host-proposed functions only and projects declared model capabilities',()=>{
  assert.throws(()=>planRequest({model:'a',input:[],tools:[{type:'web_search'}]}),{code:'unsupported_plan_tool'});
  assert.deepEqual(projectModels({models:[{slug:'a',visibility:'list',x:'omit'},{slug:'b',visibility:'hidden'}]}),
    [{slug:'a',display_name:'a',visibility:'list'}]);
});

test('filters the Codex Ultra mode from inference and preserves other catalog efforts',()=>{
  const entries=['low','xhigh','max','Ultra','custom-effort'].map(effort=>({effort}));
  const [model]=projectModels({models:[{slug:'test',visibility:'list',default_reasoning_level:'ULTRA',supported_reasoning_levels:entries}]});
  assert.deepEqual(model.supported_reasoning_levels.map(e=>e.effort),['low','xhigh','max','custom-effort']);
  assert.equal(model.default_reasoning_level,undefined);
  const req=effort=>planRequest({model:'test',input:[],reasoning:{effort,summary:'auto'},prompt_cache_key:'agy-0123456789abcdef'});
  for(const effort of ['ultra','Ultra','ULTRA'])assert.throws(()=>req(effort),{code:'unsupported_reasoning_effort',status:400});
  assert.deepEqual(req('custom-effort').reasoning,{effort:'custom-effort',summary:'auto'});
  assert.equal(req('custom-effort').prompt_cache_key,'agy-0123456789abcdef');
  assert.equal(planRequest({model:'test',input:[],prompt_cache_key:'invalid key with spaces'}).prompt_cache_key,undefined);
});

