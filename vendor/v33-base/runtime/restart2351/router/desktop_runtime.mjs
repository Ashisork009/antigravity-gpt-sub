import {createHash} from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, realpathSync, renameSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { Readable } from 'node:stream';
import { listenRoutes } from './serve.mjs';
import { openGate } from './lease/gate.mjs';
import { createCodexBackend } from './codex/backend.mjs';

const vendorHosts = new Set(['daily-cloudcode-pa.googleapis.com','generativelanguage.googleapis.com']);

export function electronVendor(fetch) {
  return async ({origin,path,method,headers,signal,body}) => {
    if (!vendorHosts.has(origin) || !path.startsWith('/') || path.startsWith('//')) throw Error('Unknown vendor endpoint');
    const url = new URL(path,'https://'+origin);
    if (url.origin !== 'https://'+origin || url.username || url.password) throw Error('Invalid vendor target');
    const outgoing = {...headers};
    delete outgoing['accept-encoding'];
    delete outgoing['content-length'];
    const options = {method,headers:outgoing,signal,credentials:'omit',redirect:'error',cache:'no-store'};
    if (body !== undefined) {
      options.body = Buffer.isBuffer(body) ? body : Readable.toWeb(body);
      options.duplex = 'half';
    }
    const result = await fetch(url.href,options);
    const stream = result.body ? Readable.fromWeb(result.body) : Readable.from([]);
    stream.statusCode = result.status;
    stream.headers = Object.fromEntries(result.headers);
    // Chromium Fetch returns decoded bytes. Do not describe them as compressed on the LS leg.
    delete stream.headers['content-encoding'];
    delete stream.headers['content-length'];
    return stream;
  };
}

function cockpitKey(config, load, lookup) {
  const url = new URL(config.baseURL);
  if (url.protocol!=='http:' || url.hostname!=='127.0.0.1' || url.port!=='53927' || url.username || url.password ||
      url.search || url.hash || !['/v1','/v1/','/v1/responses'].includes(url.pathname)) throw Error('Expected the local Cockpit Responses gateway');
  const gateway=load();
  if (gateway.enabled!==true || gateway.accessScope!=='localhost' || gateway.clientBaseUrlHost!=='localhost' ||
      gateway.port!==53927 || gateway.gatewayMode!=='native' || gateway.nativeGatewayDefaultMigrated!==true ||
      gateway.capabilityFallback?.enabled!==false || gateway.customRoutingRules?.length || gateway.modelAliases?.length ||
      gateway.accountPools?.length || !Array.isArray(gateway.accountIds) || gateway.accountIds.length!==1 ||
      typeof gateway.accountIds[0]!=='string' || !gateway.accountIds[0] || gateway.pausedAccountIds?.includes(gateway.accountIds[0])) {
    throw Error('Cockpit localhost gateway is unavailable or does not have one subscription account');
  }
  const plans=lookup(gateway.accountIds[0]);
  const expiry=plans?.[0]?.subscription_active_until;
  if (plans?.length!==1 || !['pro','chatgptpro'].includes(plans[0].plan_type?.toLowerCase()) || typeof expiry!=='string' ||
      !/(?:Z|[+-]\d\d:\d\d)$/i.test(expiry) || !(Date.parse(expiry)>Date.now())) throw Error('No active Pro subscription summary');
  return gateway.apiKey;
}

function localCockpitConfig() {
  const file=join(homedir(),'.cockpit_tools','codex_local_access.json');
  if (realpathSync.native(file).toLowerCase()!==file.toLowerCase()) throw Error('Redirected Cockpit config');
  return JSON.parse(readFileSync(file,'utf8').replace(/^\uFEFF/,''));
}

function subscriptionSummary(id) {
  const database=join(homedir(),'.cockpit_tools','codex_accounts.sqlite');
  if (realpathSync.native(database).toLowerCase()!==database.toLowerCase()) throw Error('Redirected Cockpit summary index');
  const {DatabaseSync}=createRequire(import.meta.url)('node:sqlite');
  const db=new DatabaseSync(database,{readOnly:true});
  try {
    return db.prepare('SELECT plan_type, subscription_active_until FROM summaries WHERE account_id = ?').all(id);
  } finally { db.close(); }
}

export function chooseBackend(config, env = process.env, load = localCockpitConfig, lookup = subscriptionSummary) {
  if (config.mode==='fixture') return {};
  if (config.mode!=='codex') throw Error('Unknown routing mode');
  if (config.keyEnv && config.keyEnv!=='ANTIGRAVITY_CODEX_GATEWAY_KEY') throw Error('Invalid gateway key environment variable');
  if (config.keySource && config.keySource!=='cockpit-local') throw Error('Unknown gateway key source');
  if ([config.keyEnv,config.apiKey,config.keySource].filter(Boolean).length!==1) throw Error('Choose one gateway key source');
  let memberHash=config.memberSHA256;
  if (memberHash!==undefined && !/^[0-9a-f]{64}$/.test(memberHash)) throw Error('Invalid Cockpit subscription fingerprint');
  function pinnedGateway() {
    const gateway=load();
    const id=gateway.accountIds?.[0];
    if (typeof id!=='string' || !id || gateway.accountIds.length!==1) throw Error('Expected one subscription member');
    const hash=createHash('sha256').update(id).digest('hex');
    if (memberHash!==undefined && hash!==memberHash) throw Error('Subscription membership changed');
    memberHash=hash;
    return gateway;
  }
  function backend() {
    const apiKey = config.keySource ? cockpitKey(config,pinnedGateway,lookup) : config.keyEnv ? env[config.keyEnv] : config.apiKey;
    if (typeof apiKey!=='string' || !apiKey.trim() || /[\r\n]/.test(apiKey)) throw Error('Missing gateway client key');
    return createCodexBackend({baseURL:config.baseURL,model:config.model,apiKey});
  }
  const first=backend();
  return {identity:{slug:'local-codex-subscription',label:'Codex（订阅）'},
    generate:config.keySource ? args=>backend()(args) : first};
}

function diagnostics(dir,mode) {
  const state={startedAt:new Date().toISOString(),mode,seq:0,counts:{},recent:[]};
  const file=join(dir,'diagnostics.json');
  const kinds=new Set(['catalog','probe_generation','model_generation','native_generation','request_error']);
  const keys=['operation','listener','status','added','enabled','slot_occupied','identity_collision','upstream_rows',
    'recommended_first_group_contains_probe','tool_call','tool_result','selector_field','selector','cancelled'];
  const write=()=>{
    try {writeFileSync(file+'.tmp',JSON.stringify(state));renameSync(file+'.tmp',file);}
    catch { /* A busy diagnostic reader must never interrupt inference. */ }
  };
  write();
  return (kind,fields)=>{
    if (!kinds.has(kind)) return;
    state.counts[kind]=(state.counts[kind]??0)+1;
    state.recent.push({seq:++state.seq,time:new Date().toISOString(),kind,...Object.fromEntries(keys.filter(k=>Object.hasOwn(fields,k)).map(k=>[k,fields[k]]))});
    if (state.recent.length>48) state.recent.shift();
    write();
  };
}

export async function startDesktopRouter({stateDir, fetch}) {
  const runDir=join(stateDir,'run');
  mkdirSync(runDir,{recursive:true});
  const settingsPath=join(stateDir,'settings.json');
  const config=existsSync(settingsPath) ? JSON.parse(readFileSync(settingsPath,'utf8').replace(/^\uFEFF/,'')) : {mode:'fixture'};
  const backend=chooseBackend(config);
  let gate;
  const listener=await listenRoutes(runDir,electronVendor(fetch),undefined,{
    ...backend, enabled:()=>gate?.enabled()??false,
    authorizeProbe:socket=>gate?.authorizeProbe(socket)??false, record:diagnostics(runDir,config.mode)
  });
  try {gate=openGate(listener.urls);}
  catch (err) {listener.close();throw err;}
  return {cloud:listener.urls.cloud,close(){gate.close();listener.close();}};
}
