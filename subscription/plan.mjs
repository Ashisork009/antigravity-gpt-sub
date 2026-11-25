// The gateway authenticates its own local installation using OpenAI's published SIWC flow.
import {createHash,createPublicKey,randomBytes,randomUUID,timingSafeEqual,verify} from 'node:crypto';
import {createServer} from 'node:http';
import {vault} from './vault.mjs';

const issuer='https://auth.openai.com';
const api='https://api.openai.com/v1';
const authorize=issuer+'/api/accounts/authorize';
const token=issuer+'/api/accounts/oauth/token';
const jwks=issuer+'/.well-known/jwks.json';
const usageScope='chatgpt.tokens.use.direct';
const scope='openid profile email offline_access resource.invoke '+usageScope;
const ns='antigravity';
const coded=(message,status)=>Object.assign(Error(message),{status,code:message});
const hasScope=value=>typeof value==='string' && value.split(/\s+/).includes(usageScope);
const fresh=()=>randomBytes(32).toString('base64url');
const hash=v=>createHash('sha256').update(v).digest('base64url');
const one=(params,key)=>params.getAll(key).length===1 ? params.get(key) : undefined;
const sensitiveFree={credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'};
// Codex lists Ultra alongside efforts but implements it through client-side multi-agent orchestration.
const clientMode=effort=>typeof effort==='string'&&effort.trim().toLowerCase()==='ultra';

export function planRequest(body) {
  if (!body || typeof body.model!=='string' || !body.model || !Array.isArray(body.input)) throw coded('invalid_plan_request',400);
  if (clientMode(body.reasoning?.effort)) throw coded('unsupported_reasoning_effort',400);
  const request={model:body.model,input:body.input.map(item=>{
    if (item.role==='system') throw coded('plan_requires_developer_instructions',400);
    if (item.type==='function_call') return {...item,namespace:ns};
    return item;
  }),store:false,stream:true};
  if (body.instructions!==undefined) request.instructions=body.instructions;
  if (body.reasoning!==undefined) request.reasoning=body.reasoning;
  if (body.include?.includes('reasoning.encrypted_content')) request.include=['reasoning.encrypted_content'];
  if (typeof body.prompt_cache_key==='string'&&/^[a-zA-Z0-9._:-]{1,64}$/.test(body.prompt_cache_key)) request.prompt_cache_key=body.prompt_cache_key;
  if (body.tool_choice!==undefined) {
    if (!['auto','none','required'].includes(body.tool_choice)) throw coded('unsupported_plan_tool_choice',400);
    request.tool_choice=body.tool_choice;
  }
  if (body.tools?.length) {
    for (const tool of body.tools) {
      if (tool.type!=='function' || !/^[a-zA-Z0-9_-]{1,128}$/.test(tool.name)) throw coded('unsupported_plan_tool',400);
    }
    request.tools=[{type:'namespace',name:ns,description:'Native tools executed by Antigravity.',tools:body.tools}];
  }
  return request;
}

export function projectModels(data) {
  if (!Array.isArray(data?.models)) throw coded('invalid_subscription_model_catalog',502);
  return data.models.filter(m=>m.visibility==='list' && typeof m.slug==='string').map(m=>{
    const row={slug:m.slug,display_name:m.display_name||m.slug,visibility:m.visibility};
    for (const key of ['context_window','max_input_tokens','max_output_tokens']) {
      if (Number.isSafeInteger(m[key]) && m[key]>0) row[key]=m[key];
    }
    if (Array.isArray(m.input_modalities)) row.input_modalities=m.input_modalities.filter(x=>typeof x==='string');
    if (typeof m.default_reasoning_level==='string'&&!clientMode(m.default_reasoning_level)) row.default_reasoning_level=m.default_reasoning_level;
    if (Array.isArray(m.supported_reasoning_levels)) {
      row.supported_reasoning_levels=m.supported_reasoning_levels.filter(e=>typeof e?.effort==='string'&&!clientMode(e.effort)).map(e=>({
        effort:e.effort,description:typeof e.description==='string'?e.description:''
      }));
    }
    return row;
  });
}

async function identity(jwt,client,nonce,fetch) {
  try {
    const pieces=jwt.split('.');
    if (pieces.length!==3) throw Error();
    const [h,p,s]=pieces;
    const head=JSON.parse(Buffer.from(h,'base64url'));
    const claims=JSON.parse(Buffer.from(p,'base64url'));
    if (head.alg!=='RS256' || typeof head.kid!=='string' || head.crit) throw Error();
    const res=await fetch(jwks,{...sensitiveFree,signal:AbortSignal.timeout(15000)});
    if (!res.ok) throw Error();
    const keys=(await res.json()).keys.filter(k=>k.kid===head.kid && k.kty==='RSA' &&
      (!k.use||k.use==='sig') && (!k.alg||k.alg==='RS256'));
    if (keys.length!==1 || !verify('RSA-SHA256',Buffer.from(h+'.'+p),createPublicKey({key:keys[0],format:'jwk'}),Buffer.from(s,'base64url'))) throw Error();
    const now=Date.now()/1000;
    const aud=Array.isArray(claims.aud)?claims.aud:[claims.aud];
    if (claims.iss!==issuer || !aud.includes(client) || ((aud.length>1||claims.azp) && claims.azp!==client) ||
      !Number.isFinite(claims.exp) || claims.exp<=now || !Number.isFinite(claims.iat) || claims.iat>now+60 ||
      (claims.nbf!==undefined && (!Number.isFinite(claims.nbf)||claims.nbf>now+60)) || claims.nonce!==nonce ||
      typeof claims.sub!=='string' || !claims.sub) throw Error();
    return {subject:claims.sub,email:typeof claims.email==='string'?claims.email:undefined};
  } catch {throw coded('subscription_identity_validation_failed',401);}
}

function grant(reply,oldScope) {
  if (!reply || typeof reply.access_token!=='string' || !reply.access_token || reply.token_type?.toLowerCase()!=='bearer' ||
      !Number.isFinite(reply.expires_in) || reply.expires_in<=0) throw coded('invalid_plan_token_response',401);
  const scopes=reply.scope===undefined?oldScope:reply.scope;
  if (!hasScope(scopes)) throw coded('chatgpt_plan_usage_not_granted',403);
  return {access:reply.access_token,scope:scopes,expires:Date.now()+reply.expires_in*1000};
}

export function openPlanGateway({stateDir,safeStorage,fetch,openExternal,onChange,record=()=>{},appName='Antigravity Native Model Router'}) {
  const storage=vault(stateDir,safeStorage);
  let pending,closed=false,lastError,reauthRequired=false;
  const shutdown=new AbortController();
  const signalFor=s=>s?AbortSignal.any([s,shutdown.signal]):shutdown.signal;
  const changed=()=>{if (onChange) Promise.resolve().then(onChange).catch(()=>{});};
  async function status({displayIdentity=false}={}) {
    const current=await storage.read();
    const c=current?.registration;
    return {connected:Boolean(c?.refresh&&hasScope(c?.scope)&&!reauthRequired),authorizationPending:Boolean(pending),lastError,
      ...(displayIdentity&&c?.email?{email:c.email}:{})};
  }
  async function exchange(fields) {
    const res=await fetch(token,{...sensitiveFree,method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},
      body:new URLSearchParams(fields).toString(),signal:signalFor(AbortSignal.timeout(18000))});
    if (!res.ok) {
      const error=(await res.json().catch(()=>({}))).error;
      if (error==='invalid_grant') {
        reauthRequired=true;lastError='chatgpt_reauthorization_required';changed();
      }
      throw coded(error==='invalid_grant'?'chatgpt_reauthorization_required':'chatgpt_token_exchange_failed',res.status);
    }
    return res.json();
  }
  async function signIn() {
    if (closed) throw coded('subscription_gateway_closed',503);
    if (pending) return {pending:true};
    let attempt={};
    pending=attempt;lastError=undefined;
    let timer,server,used=false;
    const finish=(error)=>{
      clearTimeout(timer);
      server?.close();
      if (pending===attempt) pending=undefined;
      if (error) lastError=error.code?.startsWith('chatgpt_')||error.code?.startsWith('subscription_')?error.code:'subscription_signin_failed';
      changed();
    };
    attempt.cancel=()=>finish(coded('subscription_signin_cancelled',499));
    try {
      const state=await storage.exclusive(async()=>{
        let s=await storage.read();
        if (!s) {s={version:1,host:'urn:uuid:'+randomUUID()};await storage.write(s);}
        return s;
      });
      if (pending!==attempt) throw coded('subscription_signin_cancelled',499);
      const old=state.registration;
      const verifier=fresh(),nonce=fresh(),expected=fresh();
      let redirect,origin;
      server=createServer(async(req,res)=>{
        const reply=(status,text)=>{
          res.writeHead(status,{'content-type':'text/plain; charset=utf-8','cache-control':'no-store',
            'content-security-policy':"default-src 'none'",'x-content-type-options':'nosniff','referrer-policy':'no-referrer'});
          res.end(text);
        };
        if (req.method!=='GET' || req.headers.host!==origin.host || !req.url?.startsWith('/auth/callback?') ||
            req.socket.remoteAddress!=='127.0.0.1') return reply(404,'Not found');
        const params=new URL(req.url,origin).searchParams;
        const actual=one(params,'state')??'';
        if (actual.length!==expected.length || !timingSafeEqual(Buffer.from(hash(actual)),Buffer.from(hash(expected)))) return reply(400,'Invalid authorization state.');
        if (used || pending!==attempt) return reply(410,'Authorization attempt expired.');
        used=true;
        try {
          if (params.has('error')) throw coded('chatgpt_consent_declined',403);
          const code=one(params,'code'),client=one(params,'client_id')??old?.client;
          if (!code || !client || !/^[A-Za-z0-9_-]{1,200}$/.test(client) || client==='dynamic_agent_client' ||
              (old?.client&&old.client!==client)) throw coded('subscription_callback_invalid',400);
          const tokens=await exchange({grant_type:'authorization_code',client_id:client,code,code_verifier:verifier,
            redirect_uri:redirect,resource:api});
          const verified=await identity(tokens.id_token,client,nonce,fetch);
          const approved=grant(tokens);
          if (old?.subject && old.subject!==verified.subject) throw coded('subscription_identity_changed',409);
          if (typeof tokens.refresh_token!=='string'||!tokens.refresh_token) throw coded('subscription_refresh_grant_missing',403);
          await storage.exclusive(async()=>{
            const live=await storage.read();
            if (pending!==attempt || live.host!==state.host || (live.registration?.client??null)!==(old?.client??null)) throw coded('subscription_registration_changed',409);
            await storage.write({...live,registration:{client,...verified,idToken:tokens.id_token,refresh:tokens.refresh_token,...approved}});
          });
          reauthRequired=false;lastError=undefined;
          reply(200,'已连接 ChatGPT 订阅。可以关闭此页并返回 Antigravity。');finish();
        } catch (e) {reply(400,'未完成订阅授权。请返回 Antigravity 查看连接状态。');finish(e);}
      });
      await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
      redirect='http://127.0.0.1:'+server.address().port+'/auth/callback';origin=new URL(redirect);
      const url=new URL(authorize);
      url.search=new URLSearchParams({client_id:old?.client??'dynamic_agent_client',ext_agent_host_id:state.host,
        ...(old?.client?{}:{agent_name_hint:appName}),response_type:'code',redirect_uri:redirect,scope,resource:api,
        state:expected,nonce,code_challenge_method:'S256',code_challenge:hash(verifier)}).toString();
      timer=setTimeout(()=>finish(coded('subscription_signin_expired',408)),10*60*1000);timer.unref?.();
      await openExternal(url.href);
      return {pending:true};
    } catch(e) {finish(e);throw e;}
  }
  async function access(stale) {
    return storage.exclusive(async()=>{
      const state=await storage.read(),c=state?.registration;
      if (!c || !hasScope(c.scope)) throw coded('chatgpt_signin_required',401);
      if (c.access!==stale && c.expires>Date.now()+90000) return c.access;
      const next=await exchange({grant_type:'refresh_token',client_id:c.client,refresh_token:c.refresh,resource:api});
      const update=grant(next,c.scope);
      if (next.refresh_token!==undefined && (typeof next.refresh_token!=='string'||!next.refresh_token)) throw coded('subscription_refresh_grant_invalid',401);
      await storage.write({...state,registration:{...c,...update,refresh:next.refresh_token??c.refresh}});
      reauthRequired=false;lastError=undefined;
      return update.access;
    });
  }
  async function request(path,body,signal) {
    if (closed) throw coded('subscription_gateway_closed',503);
    const s=signalFor(signal);s.throwIfAborted();
    let bearer=await access();
    for (let i=0;i<2;i++) {
      const headers={authorization:'Bearer '+bearer,accept:body?'text/event-stream':'application/json'};
      if (body) {
        headers['content-type']='application/json';
        if (typeof body.prompt_cache_key==='string'&&body.prompt_cache_key) headers['session-id']=body.prompt_cache_key;
      }
      const evidence=body?{model:body.model,effort:body.reasoning?.effort,
        tool_results:body.input.filter(item=>item.type==='function_call_output').length}:null;
      if(evidence)record('subscription_post',evidence);
      const response=await fetch(api+path,{...sensitiveFree,method:body?'POST':'GET',headers,signal:s,
        ...(body?{body:JSON.stringify(body)}:{})});
      if(evidence)record('subscription_http',{...evidence,status:response.status});
      if (response.ok) return response;
      if (response.status===401&&!i) {await response.body?.cancel();bearer=await access(bearer);continue;}
      const error=(await response.json().catch(()=>({})))?.error;
      const category=typeof error?.code==='string'&&/^[a-z0-9_]{1,64}$/.test(error.code)?error.code:'http_'+response.status;
      throw coded('chatgpt_plan_'+category,response.status);
    }
  }
  return {status,signIn,
    async listModels({signal}={}) {return projectModels(await (await request('/models',null,signal??AbortSignal.timeout(20000))).json());},
    respond({body,signal}) {return request('/responses',planRequest(body),signal);},
    close(){closed=true;pending?.cancel();shutdown.abort();}
  };
}

