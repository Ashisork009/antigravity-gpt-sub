import {createHash} from 'node:crypto';

export const defaultModels=Object.freeze(['gpt-6.2-sol','gpt-6.2-astra']);
export const defaultEfforts=Object.freeze(['low','medium','high','xhigh','max']);
const effortNames={none:'None',minimal:'Minimal',low:'Low',medium:'Medium',high:'High',xhigh:'Extra High',max:'Max'};
const effortOrder=Object.freeze(['none','minimal',...defaultEfforts]);
const prefix='codex-';
const legacyPrefix='ag-codex-';
// Verified in the 2.35.1 executable's Model enum. Revalidate before allowing a new build.
const slotCount=1651;
const own=(o,k)=>Object.hasOwn(o,k);
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const modelPattern=/^[a-z0-9][a-z0-9._-]{0,119}$/;
const effortPattern=/^[a-z0-9][a-z0-9_-]{0,29}$/;
export const enumName=slot=>'MODEL_PLACEHOLDER_M'+slot;
const validSlot=n=>Number.isInteger(n)&&n>=0&&n<slotCount;
const toSlot=value=>{
  if (typeof value==='string'&&value.startsWith('models/')) value=value.slice(7);
  const symbolic=typeof value==='string'&&/^MODEL_PLACEHOLDER_M(\d+)$/.exec(value);
  const n=symbolic?Number(symbolic[1]):typeof value==='number'||typeof value==='string'&&/^\d+$/.test(value)?Number(value)-1000:NaN;
  return validSlot(n)?n:undefined;
};
function settingList(values,pattern) {
  if(!Array.isArray(values)||values.some(v=>typeof v!=='string'||!pattern.test(v))) throw Error('Invalid model router selection');
  return [...new Set(values)];
}
export function preferences(data) {
  if(data===undefined) return {version:1,models:[...defaultModels],efforts:[...defaultEfforts]};
  if(!object(data)||data.version!==1) throw Error('Unknown model router preferences version');
  return {version:1,models:settingList(data.models,modelPattern),efforts:nativeEfforts(data.efforts)};
}
// A saved selection is a set. Its insertion order depends on the order of checkbox clicks.
// Older releases also saved Ultra, a Codex client mode with its own agent orchestration.
function nativeEfforts(values) {
  if(!Array.isArray(values))throw Error('Invalid model router selection');
  const selected=settingList(values.filter(value=>typeof value!=='string'||value.toLowerCase()!=='ultra'),effortPattern);
  return [...effortOrder.filter(effort=>selected.includes(effort)),...selected.filter(effort=>!effortOrder.includes(effort))];
}
export function modelTitle(model,displayName) {
  const match=/^gpt-(\d+(?:\.\d+)*)(?:-(.+))?$/.exec(model);
  if(!match)return typeof displayName==='string'&&displayName.trim()?displayName.trim():model;
  const words=match[2]?.split('-').filter(Boolean).map(word=>word[0].toUpperCase()+word.slice(1))??[];
  return ['GPT-'+match[1],...words].join(' ');
}
export function modelCapabilities(raw) {
  if(!Array.isArray(raw)) throw Error('Missing subscription model catalog');
  const out=new Map();
  for(const row of raw) {
    if(!object(row)||typeof row.slug!=='string'||!modelPattern.test(row.slug)||row.visibility==='hide') continue;
    if(out.has(row.slug)) throw Error('Duplicate subscription model '+row.slug);
    const supported=Array.isArray(row.supported_reasoning_levels)?row.supported_reasoning_levels:[];
    const efforts=nativeEfforts(supported.map(r=>r?.effort));
    out.set(row.slug,{model:row.slug,title:modelTitle(row.slug,row.display_name),efforts,defaultEffort:row.default_reasoning_level,source:row});
  }
  return out;
}
function occupiedSlots(catalog) {
  const result=new Set();
  function visit(value,key='') {
    if(Array.isArray(value)) {for(const item of value)visit(item,key);return;}
    if(object(value)) {for(const [k,v] of Object.entries(value)){visit(k);visit(v,k);}return;}
    if(typeof value==='string'&&value.includes('MODEL_PLACEHOLDER_M')||/^(model|modelId|model_id|enum|planModel)$/.test(key)) {
      const n=toSlot(value);if(n!==undefined)result.add(n);
    }
  }
  visit(catalog);
  return result;
}
const familyId=model=>prefix+model;
const routeId=(model,effort)=>familyId(model)+'-'+effort;
const displayEffort=effort=>own(effortNames,effort)?effortNames[effort]:effort;
function migrateLegacySlug(slug) {
  if (typeof slug!=='string'||!slug.startsWith(legacyPrefix)) return null;
  const match=/^ag-codex-([1-9][0-9]{0,2})-([a-z0-9._-]+)$/.exec(slug);
  if (!match) return null;
  const n=Number(match[1]),rest=match[2];
  if (n>120||rest[n]!=='-') return null;
  const model=rest.slice(0,n),effort=rest.slice(n+1);
  if (!modelPattern.test(model)||!effortPattern.test(effort)) return null;
  return routeId(model,effort);
}
function pickSlot(slug,used,occupied) {
  const start=createHash('sha256').update(slug).digest().readUInt32BE(0)%slotCount;
  for(let i=0;i<slotCount;i++) {
    const slot=(start+i)%slotCount;
    if(!used.has(slot)&&!occupied.has(slot))return slot;
  }
}
function mapEntry(cap,effort,slot) {
  const row={displayName:cap.title+' ('+displayEffort(effort)+')',model:enumName(slot),
    apiProvider:'API_PROVIDER_GOOGLE_GEMINI',modelProvider:'MODEL_PROVIDER_GOOGLE',tokenizerType:'LLAMA_WITH_SPECIAL',
    supportsThinking:effort!=='none'};
  const limit=cap.source.context_window??cap.source.max_input_tokens;
  if(Number.isSafeInteger(limit)&&limit>0)row.maxTokens=limit;
  if(Number.isSafeInteger(cap.source.max_output_tokens)&&cap.source.max_output_tokens>0)row.maxOutputTokens=cap.source.max_output_tokens;
  if(Array.isArray(cap.source.input_modalities)){
    const supportsImages=cap.source.input_modalities.includes('image');
    row.supportsImages=supportsImages;
    if(supportsImages){
      row.supportedMimeTypes={'image/jpeg':true,'image/png':true,'image/webp':true,'image/gif':true};
    }
  }
  return row;
}
function reserveStrings(value,out) {
  if(typeof value==='string') {out.add(value.replace(/^models\//,'').toLowerCase());return;}
  if(Array.isArray(value)) {for(const item of value)reserveStrings(item,out);return;}
  if(object(value)) for(const [k,v] of Object.entries(value)){out.add(k.toLowerCase());reserveStrings(v,out);}
}
/**
 * The original upstream JSON object is never mutated. The host must bind the returned
 * state to the authenticated catalog's account/project and drop it on disable/refresh failure.
 */
export function compileCatalog(upstream,rawModels,settings,assignments={},enabled=true) {
  const selected=preferences(settings),capabilities=modelCapabilities(rawModels);
  const used=new Set(),allocated={};
  for(const [rawSlug,n] of Object.entries(assignments)){
    const slug=rawSlug.startsWith(prefix)?rawSlug:migrateLegacySlug(rawSlug);
    if(!slug||!validSlot(n)||used.has(n))throw Error('Invalid persisted model slot');
    if(own(allocated,slug))throw Error('Invalid persisted model slot');
    used.add(n);allocated[slug]=n;
  }
  const routes=new Map(),blocked=[],conflictingSlugs=new Set(),reserved=new Set();
  const nativeSlugs=new Set(Object.keys(upstream?.models??{}).map(s=>s.replace(/^models\//,'')));
  const occupied=occupiedSlots(upstream);
  const result={catalog:upstream,routes,blocked,conflictingSlugs,nativeSlugs,occupied,assignments:allocated};
  if(!enabled||!selected.models.length||!selected.efforts.length)return result;
  const groupsKey=own(upstream,'grouped_models')?'grouped_models':'groupedModels';
  const sortsKey=own(upstream,'agent_model_sorts')?'agent_model_sorts':'agentModelSorts';
  const sorts=upstream[sortsKey],groups=upstream[groupsKey]??{};
  if(!object(upstream.models)||!object(groups)||!Array.isArray(sorts))throw Error('Unsupported native Cloud Code catalog');
  const recommended=sorts.find(s=>String(s.displayName??s.display_name??s.name).toLowerCase()==='recommended');
  const first=recommended?.groups?.[0];
  const idsKey=first&&own(first,'model_ids')?'model_ids':'modelIds';
  if(!Array.isArray(first?.[idsKey]))throw Error('Unsupported native Recommended group');
  reserveStrings(upstream,reserved);
  const additions={},families={};
  for(const model of selected.models) {
    const cap=capabilities.get(model),base=familyId(model);
    if(!cap) {blocked.push({model,reason:'unavailable_model'});continue;}
    if(reserved.has(base)||Object.values(groups).some(g=>(g?.displayName??g?.display_name)?.toLowerCase()===cap.title.toLowerCase())) {
      blocked.push({model,reason:'family_collision'});continue;
    }
    const levels=[];
    for(const effort of selected.efforts)if(!cap.efforts.includes(effort))blocked.push({model,effort,reason:'unsupported_effort'});
    for(const effort of cap.efforts) {
      if(!selected.efforts.includes(effort))continue;
      const slug=routeId(model,effort),name=cap.title+' ('+displayEffort(effort)+')';
      if(reserved.has(slug)||reserved.has(name.toLowerCase())||routes.has(slug)){
        conflictingSlugs.add(slug);blocked.push({model,effort,reason:'identity_collision'});continue;
      }
      const slot=allocated[slug]??pickSlot(slug,used,occupied);
      if(slot===undefined||occupied.has(slot)){
        blocked.push({model,effort,reason:slot===undefined?'no_free_slot':'native_owns_reserved_slot'});continue;
      }
      used.add(slot);allocated[slug]=slot;
      routes.set(slug,{slug,model,effort,slot,enum:enumName(slot),value:1000+slot});
      additions[slug]=mapEntry(cap,effort,slot);
      levels.push({thinkingSuffix:effort,thinkingDisplayName:displayEffort(effort)});
    }
    if(levels.length) families[base]={displayName:cap.title,supportedThinkingLevels:levels,
      defaultThinkingSuffix:levels.some(l=>l.thinkingSuffix===cap.defaultEffort)?cap.defaultEffort:levels[0].thinkingSuffix};
  }
  if(routes.size) result.catalog={...upstream,models:{...upstream.models,...additions},[groupsKey]:{...groups,...families},
    [sortsKey]:sorts.map(s=>s===recommended?{...s,groups:[{...first,[idsKey]:[...first[idsKey],...routes.keys()]},...s.groups.slice(1)]}:s)};
  return result;
}
export function resolveRoute(values,state) {
  if(!Array.isArray(values)||!values.length)return {kind:'native'};
  const clean=values.map(v=>typeof v==='string'?v.replace(/^models\//,''):v);
  const slugs=clean.filter(v=>typeof v==='string'&&(v.startsWith(prefix)||v.startsWith(legacyPrefix)));
  if(slugs.length) {
    const slug=slugs[0];
    if(state?.nativeSlugs.has(slug)&&!own(state.assignments,slug))return {kind:'native'};
    if(slug.startsWith(legacyPrefix))return {kind:'error',status:409,reason:'subscription_selection_unavailable'};
    if(state?.conflictingSlugs.has(slug))return {kind:'error',status:409,reason:'ambiguous_model_identity'};
    const row=state?.routes.get(slug);
    if(!row)return {kind:'error',status:409,reason:'subscription_selection_unavailable'};
    if(!clean.every(v=>v===slug||toSlot(v)===row.slot))return {kind:'error',status:409,reason:'conflicting_selectors'};
    return {kind:'subscription',...row};
  }
  if(state) {
    const slots=new Set(clean.map(toSlot).filter(n=>n!==undefined));
    const owned=Object.values(state.assignments).some(n=>slots.has(n)&&!state.occupied.has(n));
    if(owned)return {kind:'error',status:409,reason:'expected_native_model_slug'};
  }
  return {kind:'native'};
}
