import {createHash} from 'node:crypto';
import {responseRequest,events,chunk,finish,outputParts} from '../restart2351/router/codex/backend.mjs';

const prefix='AGYPLAN1:';
const encodedPrefix=Buffer.from(prefix).toString('base64');
const geminiSkipSignature='skip_thought_signature_validator';
const systemPreamble='The following is a <SYSTEM_MESSAGE> not actually sent by the user. It is provided by the system as important information to pay attention to.\n\n';
const systemOpen='<SYSTEM_MESSAGE>\n';
const systemClose='</SYSTEM_MESSAGE>';
const developerTrigger='Proceed with the runtime system message above.';
const limit=8*1024*1024;
const failure=(message,status=502)=>Object.assign(Error(message),{status,code:message});
const signature=p=>p?.thoughtSignature??p?.thought_signature;
const ours=s=>typeof s==='string'&&s.startsWith(encodedPrefix);
const isReasoning=item=>item?.type==='reasoning'&&typeof item.encrypted_content==='string'&&item.encrypted_content.length>0;
const isCallPart=part=>Boolean(part&&(part.functionCall||part.function_call));
const isGeminiTarget=selector=>typeof selector==='string'&&/^(?:models\/)?gemini-/i.test(selector.trim());
const isPlainObject=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);

function canonicalize(value,sortRequired=false) {
  if (Array.isArray(value)) return value.map(v=>canonicalize(v,sortRequired));
  if (!isPlainObject(value)) return value;
  const out={};
  for (const key of Object.keys(value).sort()) {
    const v=value[key];
    if (sortRequired&&key==='required'&&Array.isArray(v)&&v.every(item=>typeof item==='string')) {
      out[key]=[...v].sort();
    } else {
      out[key]=canonicalize(v,sortRequired);
    }
  }
  return out;
}
const digest8=text=>createHash('sha256').update(text).digest('hex').slice(0,8);

// Retain opaque model state inside the host's tool-call part. The gateway stores no conversation or call ledger.
function unpack(value,model) {
  if (!ours(value)) return [];
  if (value.length>limit) throw failure('oversized_plan_reasoning_signature',400);
  let saved;
  try {saved=JSON.parse(Buffer.from(value,'base64').subarray(prefix.length).toString());}
  catch {throw failure('invalid_plan_reasoning_signature',400);}
  if (typeof saved?.model!=='string'||!Array.isArray(saved.items)||!saved.items.every(isReasoning)) throw failure('invalid_plan_reasoning_signature',400);
  return saved.model===model?saved.items:[];
}

export function stripPlanSignatures(contents,targetSelector) {
  if (!Array.isArray(contents)) return contents;
  const gemini=isGeminiTarget(targetSelector);
  let changed=false;
  const rows=contents.map(turn=>{
    if (!Array.isArray(turn?.parts))return turn;
    if (!turn.parts.some(part=>ours(signature(part))))return turn;
    changed=true;
    return {...turn,parts:turn.parts.map(part=>{
      const sig=signature(part);
      if (!ours(sig)) return part;
      const out={...part};
      delete out.thoughtSignature;
      delete out.thought_signature;
      if (gemini&&isCallPart(part)) out.thoughtSignature=geminiSkipSignature;
      return out;
    })};
  });
  return changed?rows:contents;
}

// Canonicalize functionCall.args and functionResponse.response maps before passing to the frozen v3.3 codec
// so Go ProtoJSON map iteration randomness in history never busts OpenAI's prompt KV cache.
function canonicalizePayload(payload) {
  if (!Array.isArray(payload?.contents)) return payload;
  let changed=false;
  const contents=payload.contents.map(turn=>{
    if (!Array.isArray(turn?.parts)) return turn;
    let turnChanged=false;
    const parts=turn.parts.map(part=>{
      const call=part?.functionCall??part?.function_call;
      if (call&&isPlainObject(call.args)) {
        turnChanged=true;changed=true;
        const cleanCall={...call,args:canonicalize(call.args)};
        return part.functionCall?{...part,functionCall:cleanCall}:{...part,function_call:cleanCall};
      }
      const result=part?.functionResponse??part?.function_response;
      if (result&&isPlainObject(result.response)) {
        turnChanged=true;changed=true;
        const cleanResult={...result,response:canonicalize(result.response)};
        return part.functionResponse?{...part,functionResponse:cleanResult}:{...part,function_response:cleanResult};
      }
      return part;
    });
    return turnChanged?{...turn,parts}:turn;
  });
  return changed?{...payload,contents}:payload;
}

// Antigravity injects runtime <SYSTEM_MESSAGE> notifications (e.g. subagent dispatches and
// send_message deliveries) inside Gemini role:"user" turns. Strictly promote standalone
// runtime blocks to role:"developer" while never promoting anything inside <USER_REQUEST>.
function extractRuntimeSystemText(text) {
  if (typeof text!=='string'||!text.includes(systemOpen)||text.includes('<USER_REQUEST>')||text.includes('</USER_REQUEST>')) return null;
  const normalized=text.replace(/\r\n/g,'\n');
  let pos=0;
  const blocks=[];
  while (pos<normalized.length) {
    while (pos<normalized.length&&/\s/.test(normalized[pos])) pos++;
    if (pos>=normalized.length) break;
    if (!normalized.startsWith(systemPreamble+systemOpen,pos)) return null;
    const bodyStart=pos+systemPreamble.length;
    let searchFrom=bodyStart+systemOpen.length;
    let closeAt=-1;
    while (true) {
      const idx=normalized.indexOf(systemClose,searchFrom);
      if (idx<0) return null;
      const after=idx+systemClose.length;
      let next=after;
      while (next<normalized.length&&/\s/.test(normalized[next])) next++;
      if (next>=normalized.length||normalized.startsWith(systemPreamble+systemOpen,next)) {
        closeAt=after;pos=next;break;
      }
      searchFrom=after;
    }
    blocks.push(normalized.slice(bodyStart,closeAt));
  }
  return blocks.length?blocks.join('\n\n'):null;
}

function promoteRuntimeSystemItems(input) {
  const out=[];
  for (const item of input) {
    if (item.role!=='user'||!Array.isArray(item.content)) {out.push(item);continue;}
    if (item.content.some(p=>p?.type==='input_text'&&typeof p.text==='string'&&/<\/?USER_REQUEST>/.test(p.text))) {
      out.push(item);continue;
    }
    let activeRole=null,bucket=[];
    const flush=()=>{if (bucket.length) {out.push({role:activeRole,content:bucket});bucket=[];}};
    for (const part of item.content) {
      const promoted=part?.type==='input_text'?extractRuntimeSystemText(part.text):null;
      const nextRole=promoted!==null?'developer':'user';
      const nextPart=promoted!==null?{type:'input_text',text:promoted}:part;
      if (activeRole!==nextRole) {flush();activeRole=nextRole;}
      bucket.push(nextPart);
    }
    flush();
  }
  let leadDev=0;
  while (leadDev<out.length&&out[leadDev].role==='developer') leadDev++;
  if (leadDev>0&&out[leadDev]?.role!=='user') {
    out.splice(leadDev,0,{role:'user',content:[{type:'input_text',text:developerTrigger}]});
  }
  return out;
}

// Hash only model + initial conversation turn (stripped of any trailing ephemeral runtime reminder)
// so dynamic systemInstruction or ephemeral reminders never bounce cache shards.
function cacheSeed(input) {
  const seed=input.find(item=>item.role==='user'||item.role==='developer')??input[0]??null;
  if (!seed||!Array.isArray(seed.content)) return seed;
  return {
    role:seed.role,
    content:seed.content.map(part=>{
      if (part?.type!=='input_text'||typeof part.text!=='string') return part;
      const idx=part.text.indexOf(systemPreamble+systemOpen);
      return idx>0?{...part,text:part.text.slice(0,idx).trimEnd()}:part;
    }),
  };
}

function cacheKey(model,input) {
  return 'agy-'+createHash('sha256').update(JSON.stringify([model,cacheSeed(input)])).digest('hex').slice(0,32);
}

function inputs(payload,model,effort) {
  if (typeof effort!=='string'||!effort)throw failure('missing_selected_reasoning_effort',400);
  const sanitized=canonicalizePayload(payload);
  let body;
  try {body=responseRequest(sanitized,model,true);}
  catch (err) {
    if (err?.status) throw err;
    throw failure('subscription_unsupported_input',400);
  }
  // Canonicalize tool order and parameter schema keys so Go map iteration randomness does not bust KV cache.
  if (Array.isArray(body.tools)&&body.tools.length) {
    body.tools=[...body.tools]
      .sort((a,b)=>a.name<b.name?-1:a.name>b.name?1:0)
      .map(tool=>({...tool,parameters:canonicalize(tool.parameters,true)}));
  }
  body.reasoning={effort,summary:'auto'};
  body.include=['reasoning.encrypted_content'];
  const saved=[];
  for(const turn of payload.contents) for(const part of turn.parts??[]) {
    if(part.functionCall||part.function_call) saved.push(unpack(signature(part),model));
  }
  let index=0;
  const conversationInput=promoteRuntimeSystemItems(
    body.input.flatMap(item=>item.type==='function_call'?[...(saved[index++]??[]),item]:[item])
  );
  // Compute per-conversation prompt_cache_key before prepending shared system instructions.
  body.prompt_cache_key=cacheKey(model,conversationInput);
  // Starting with GPT-6.2, top-level `instructions` is appended after `input` and billed uncached.
  // Placing reusable system instructions as the leading `developer` message in `input` enables full KV caching.
  const sysText=typeof body.instructions==='string'&&body.instructions.trim()?body.instructions:'';
  delete body.instructions;
  body.input=sysText
    ?[{role:'developer',content:[{type:'input_text',text:sysText}]},...conversationInput]
    :conversationInput;
  const cacheMeta={
    inst_hash:digest8(sysText),
    tools_hash:digest8(JSON.stringify(body.tools??[])),
    first_hash:digest8(JSON.stringify(conversationInput[0]??null)),
    cache_key:body.prompt_cache_key.slice(0,16),
    input_items:body.input.length,
  };
  return {body,cacheMeta};
}

function summaryText(item) {
  if (!Array.isArray(item?.summary)) return '';
  return item.summary.filter(s=>s?.type==='summary_text'&&typeof s.text==='string'&&s.text).map(s=>s.text).join('\n\n');
}

function terminalChunk(model,parts,reason,usage) {
  const frame=chunk(model,parts,reason,usage);
  if (usage&&frame.usageMetadata) {
    const cached=usage.input_tokens_details?.cached_tokens;
    if (Number.isSafeInteger(cached)&&cached>0) {
      frame.usageMetadata.cachedContentTokenCount=Math.min(cached,frame.usageMetadata.promptTokenCount);
    }
    const thoughts=usage.output_tokens_details?.reasoning_tokens;
    if (Number.isSafeInteger(thoughts)&&thoughts>0) {
      frame.usageMetadata.thoughtsTokenCount=thoughts;
      frame.usageMetadata.candidatesTokenCount=Math.max(0,(usage.output_tokens??0)-thoughts);
    }
  }
  return frame;
}

function messageText(item) {
  let out='';
  for (const p of item?.content??[]) {
    if (p?.type==='output_text'&&typeof p.text==='string') out+=p.text;
    else if (p?.type==='refusal'&&typeof p.refusal==='string') out+=p.refusal;
  }
  return out;
}

function finalParts(items,textStreamed,thoughtSeen,model,allowed) {
  if(!Array.isArray(items)) throw failure('subscription_output_missing');
  const parts=[],calls=new Set(),seen=new Set();
  let reasoning=[],taggedCall=false;
  for(const item of items) {
    if(item.type==='reasoning') {
      if(isReasoning(item))reasoning.push(item);
      if(!thoughtSeen.has(item.id)) {
        const text=summaryText(item);
        if(text) parts.push({text,thought:true});
      }
      continue;
    }
    if(item.type==='function_call') {
      if(item.namespace && item.namespace!=='antigravity') throw failure('subscription_tool_namespace_mismatch');
      if(!allowed.has(item.name)||!item.call_id||calls.has(item.call_id)) throw failure('subscription_unexpected_tool');
      const [part]=outputParts([item],seen,calls);
      if(reasoning.length||!taggedCall) {
        const state=Buffer.from(prefix+JSON.stringify({model,items:reasoning})).toString('base64');
        if(state.length>limit)throw failure('oversized_plan_reasoning_signature');
        part.thoughtSignature=state;reasoning=[];taggedCall=true;
      }
      parts.push(part);
    } else if(item.type==='message') {
      const streamed=textStreamed.get(item.id)??'';
      if (!streamed) {
        parts.push(...outputParts([item],seen,calls));
      } else {
        const full=messageText(item);
        if (full.startsWith(streamed)&&full.length>streamed.length) parts.push({text:full.slice(streamed.length)});
      }
    } else {
      throw failure('subscription_unsupported_output_item');
    }
  }
  return parts;
}

function streamFailure(event) {
  const code=event.response?.error?.code??event.code??event.error?.code;
  if(typeof code!=='string'||!/^[a-z][a-z0-9_]{0,63}$/.test(code))return failure('subscription_generation_failed');
  const status=code==='subscription_sharing_unsupported_capability'?400:code==='subscription_sharing_user_not_eligible'?403:code==='subscription_sharing_usage_unavailable'?503:
    ['rate_limit_exceeded','subscription_sharing_usage_limit_exceeded','insufficient_quota'].includes(code)?429:502;
  return failure('chatgpt_plan_'+code,status);
}

// A compatible body must be verifiable Responses SSE, including when the server sends a generic MIME.
async function* responseBytes(response,record,model,effort) {
  const media=(response.headers.get('content-type')??'').split(';')[0].trim().toLowerCase();
  const mime=/^[a-z0-9.+-]+\/[a-z0-9.+-]+$/.test(media)?media:'unspecified';
  record('upstream_body',{model,effort,mime,has_body:Boolean(response.body)});
  if(!response.ok||!response.body)throw failure('subscription_stream_unavailable',response.ok?502:response.status);
  if(mime==='text/event-stream'){yield* response.body;return;}
  const reader=response.body.getReader();
  try{
    const pieces=[];
    let bytes=0,head='';
    while(bytes<8192){
      const {value,done}=await reader.read();if(done)break;
      pieces.push(value);bytes+=value.length;
      head=Buffer.concat(pieces,bytes).subarray(0,8192).toString('utf8').trimStart();
      if(head.includes('\n')||head.startsWith('<')||head.startsWith('{')&&head.endsWith('}'))break;
    }
    if(!/^(?:event:|data:|:)/.test(head)){
      const shape=head.startsWith('<')?'html':head.startsWith('{')?'json':head?'other':'empty';
      record('upstream_unexpected_format',{model,effort,mime,reason:shape});
      if(shape==='json'){
        try{const data=JSON.parse(head);if(data.error?.code)throw streamFailure({error:data.error});}
        catch(e){if(e.code?.startsWith('chatgpt_plan_'))throw e;}
      }
      throw failure('subscription_expected_sse_received_'+shape);
    }
    for(const piece of pieces)yield piece;
    while(true){const {value,done}=await reader.read();if(done)return;yield value;}
  }finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
}

export function makeGenerate(gateway,record=()=>{}) {
  return async function* generate({payload,model,effort,signal,stream=true}) {
    const {body,cacheMeta}=inputs(payload,model,effort);
    const allowed=new Set(body.tools.map(tool=>tool.name));
    const guard=new AbortController(), combined=signal?AbortSignal.any([guard.signal,signal]):guard.signal;
    let deltas=0;
    try {
      const response=await gateway.respond({body,signal:combined});
      const textStreamed=new Map(),thoughtSeen=new Set(),thoughtParts=new Map();
      for await(const event of events(responseBytes(response,record,model,effort))) {
        combined.throwIfAborted();
        if (event.type==='error'||event.type==='response.failed'||event.type==='response.cancelled')throw streamFailure(event);
        if (stream&&event.type==='response.reasoning_summary_text.delta') {
          if(event.delta){
            const itemKey=event.item_id??'reasoning',partIndex=event.summary_index??0;
            const prev=thoughtParts.get(itemKey);
            const text=prev!==undefined&&prev!==partIndex?'\n\n'+event.delta:event.delta;
            thoughtParts.set(itemKey,partIndex);thoughtSeen.add(itemKey);deltas++;
            yield chunk(model,[{text,thought:true}]);
          }
        } else if (stream&&(event.type==='response.output_text.delta'||event.type==='response.refusal.delta')) {
          if(event.delta){
            deltas++;
            const key=event.item_id??'message';
            textStreamed.set(key,(textStreamed.get(key)??'')+event.delta);
            yield chunk(model,[{text:event.delta}]);
          }
        } else if(event.type==='response.completed'||event.type==='response.incomplete') {
          const r=event.response;
          if(!r||r.status!==event.type.slice('response.'.length))throw failure('subscription_terminal_state_mismatch');
          const reason=finish(r);
          if(reason==='MAX_TOKENS' && r.incomplete_details?.reason!=='max_output_tokens')throw failure('subscription_unknown_incomplete_reason');
          const parts=finalParts(r.output,textStreamed,thoughtSeen,model,allowed);
          if(reason!=='STOP' && parts.some(p=>p.functionCall))throw failure('subscription_incomplete_tool_call');
          const hasVisible=[...textStreamed.values()].some(t=>t.length>0)||
            parts.some(p=>p.functionCall||(!p.thought&&typeof p.text==='string'&&p.text.length>0));
          if(reason==='STOP' && !hasVisible)throw failure('subscription_empty_output');
          record('upstream_terminal',{
            model,effort,deltas,reason:r.status,tool_calls:parts.filter(p=>p.functionCall).length,
            out_types:(r.output??[]).map(item=>item?.type??'unknown').join(','),
            input_tokens:r.usage?.input_tokens??0,
            cached_tokens:r.usage?.input_tokens_details?.cached_tokens??0,
            output_tokens:r.usage?.output_tokens??0,
            reasoning_tokens:r.usage?.output_tokens_details?.reasoning_tokens??0,
            ...cacheMeta,
          });
          yield terminalChunk(model,parts,reason,r.usage);
          return;
        }
      }
      throw failure('subscription_stream_ended_without_status');
    } finally {
      if(signal?.aborted)record('upstream_cancel',{model,effort,deltas,cancelled:combined.aborted});
      guard.abort();
    }
  };
}
