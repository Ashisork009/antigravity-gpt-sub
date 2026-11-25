// Inference transport only. The caller owns context, tools and their execution.
import http from 'node:http';
import https from 'node:https';
import { createHash } from 'node:crypto';

const cap = 32 * 1024 * 1024;
const isObject = value => value && typeof value === 'object' && !Array.isArray(value);
const jsonText = value => typeof value === 'string' ? value : JSON.stringify(value);
// ProtoJSON writes Google's int64 schema bounds as strings. JSON Schema
// validates these keywords as integers even when function strict mode is off.
const integerBounds = new Set(['minItems','maxItems','minLength','maxLength','minProperties','maxProperties']);

function parameters(schema) {
  if (Array.isArray(schema)) return schema.map(parameters);
  if (!isObject(schema)) return schema;
  const copy = Object.create(null);
  for (const [key,value] of Object.entries(schema)) {
    if (key === 'type' && typeof value === 'string') copy.type = value.toLowerCase();
    else if (integerBounds.has(key) && typeof value==='string') {
      const n=Number(value);
      if (!/^\d+$/.test(value) || !Number.isSafeInteger(n)) throw Error('Invalid integer schema bound '+key);
      copy[key]=n;
    }
    else if (key === 'properties' || key === '$defs') {
      copy[key] = Object.fromEntries(Object.entries(value).map(([name,definition])=>[name,parameters(definition)]));
    } else if (key === 'enum' || key === 'const' || key === 'default') copy[key]=value;
    else if (key !== 'propertyOrdering' && key !== 'nullable') copy[key] = parameters(value);
  }
  if (schema.nullable && typeof copy.type==='string') copy.type=[copy.type,'null'];
  return copy;
}

function image(part) {
  const blob=part.inlineData ?? part.inline_data;
  if (!blob || !/^image\/(?:jpeg|png|webp|gif)$/i.test(blob.mimeType ?? blob.mime_type) ||
      typeof blob.data!=='string') throw Error('Unsupported inline media');
  return {type:'input_image',image_url:'data:'+(blob.mimeType ?? blob.mime_type)+';base64,'+blob.data};
}

export function responseRequest(payload, model, stream) {
  if (!Array.isArray(payload.contents)) throw Error('Missing host conversation');
  const input=[];
  const pending=new Map();
  const tools=(payload.tools ?? []).flatMap(group=>(group.functionDeclarations ?? group.function_declarations ?? []).map(fn=>({
    type:'function',name:fn.name,description:fn.description ?? '',
    parameters:parameters(fn.parametersJsonSchema ?? fn.parameters_json_schema ?? fn.parameters ?? {type:'object',properties:{}}),
    strict:false
  })));
  for (const [index,turn] of payload.contents.entries()) {
    const role=turn.role==='model'?'assistant':'user';
    let content=[];
    const flush=()=>{ if (content.length) { input.push({role,content}); content=[]; } };
    for (const [partIndex,part] of (turn.parts ?? []).entries()) {
      const call=part.functionCall ?? part.function_call;
      const result=part.functionResponse ?? part.function_response;
      if (call) {
        flush();
        const id=String(call.id || 'call_'+createHash('sha256').update(JSON.stringify([index,partIndex,call])).digest('hex').slice(0,24));
        pending.set(id,call.name);
        input.push({type:'function_call',call_id:id,name:call.name,arguments:jsonText(call.args ?? {})});
      } else if (result) {
        flush();
        const candidates=[...pending].filter(([,name])=>name===result.name);
        const id=result.id || (candidates.length===1?candidates[0][0]:undefined);
        if (!id || pending.get(id)!==result.name) throw Error('Unmatched native tool result');
        pending.delete(id);
        const inline=(result.parts ?? []).filter(p=>p.inlineData || p.inline_data).map(image);
        const text=jsonText(result.response ?? {});
        input.push({type:'function_call_output',call_id:id,output:inline.length?[{type:'input_text',text},...inline]:text});
      } else if (part.thought) {
        continue;
      } else if (typeof part.text==='string') {
        if (part.text) content.push({type:role==='assistant'?'output_text':'input_text',text:part.text});
      } else if (part.inlineData || part.inline_data) {
        content.push(image(part));
      } else if (part.fileData || part.file_data) {
        throw Error('Host must supply inline media for an external inference request');
      } else if (Object.keys(part).some(k=>!['thoughtSignature','thought_signature'].includes(k))) {
        throw Error('Unsupported host content part');
      }
    }
    flush();
  }
  const req={model,stream,store:false,input,tools};
  const config=payload.toolConfig?.functionCallingConfig ?? payload.tool_config?.function_calling_config;
  const allow=config?.allowedFunctionNames ?? config?.allowed_function_names;
  if (Array.isArray(allow) && allow.length) req.tools=tools.filter(t=>allow.includes(t.name));
  if (config?.mode==='NONE') req.tool_choice='none';
  else if (config?.mode==='ANY') req.tool_choice='required';
  const instruction=payload.systemInstruction ?? payload.system_instruction;
  if (instruction?.parts?.length) req.instructions=instruction.parts.map(p=>p.text ?? '').join('\n');
  const limit=payload.generationConfig?.maxOutputTokens ?? payload.generation_config?.max_output_tokens;
  if (Number.isSafeInteger(limit) && limit>0) req.max_output_tokens=limit;
  return req;
}

function chunk(model,parts,reason,usage) {
  const candidate={index:0,content:{role:'model',parts}};
  if (reason) candidate.finishReason=reason;
  const frame={modelVersion:model,candidates:[candidate]};
  if (usage) frame.usageMetadata={promptTokenCount:usage.input_tokens ?? 0,
    candidatesTokenCount:usage.output_tokens ?? 0,totalTokenCount:usage.total_tokens ?? 0};
  return frame;
}

function tool(item) {
  if (typeof item.name!=='string' || !item.call_id) throw Error('Incomplete tool call');
  const args=JSON.parse(item.arguments || '{}');
  if (!isObject(args)) throw Error('Invalid tool arguments');
  return {functionCall:{name:item.name,id:item.call_id,args}};
}

function finish(response) {
  if (response.status==='completed') return 'STOP';
  if (response.status==='incomplete') return response.incomplete_details?.reason==='content_filter'?'SAFETY':'MAX_TOKENS';
  throw Error('Local subscription gateway did not complete the response');
}

async function* events(body) {
  const decoder=new TextDecoder();
  let rest='',data=[];
  for await(const bytes of body) {
    rest+=decoder.decode(bytes,{stream:true});
    if (rest.length>cap) throw Error('Gateway event is too large');
    let i;
    while ((i=rest.indexOf('\n'))>=0) {
      const line=rest.slice(0,i).replace(/\r$/,''); rest=rest.slice(i+1);
      if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
      if (!line && data.length) {
        const value=data.join('\n');data=[];
        if (value!=='[DONE]') yield JSON.parse(value);
      }
    }
  }
  rest+=decoder.decode();
  if (rest.startsWith('data:')) data.push(rest.slice(5).trim());
  if (data.length && data.join('\n')!=='[DONE]') yield JSON.parse(data.join('\n'));
}

function outputParts(items,textSeen,calls) {
  const parts=[];
  for (const item of items ?? []) {
    if (item.type==='function_call' && !calls.has(item.call_id)) {
      parts.push(tool(item));calls.add(item.call_id);
    } else if (item.type==='message' && !textSeen.has(item.id)) {
      for (const p of item.content ?? []) {
        if (p.type==='output_text' && p.text) parts.push({text:p.text});
        if (p.type==='refusal' && p.refusal) parts.push({text:p.refusal});
      }
      textSeen.add(item.id);
    }
  }
  return parts;
}

export function createCodexBackend({baseURL,model,apiKey}) {
  const url=new URL(baseURL);
  if (!['http:','https:'].includes(url.protocol) || !['127.0.0.1','[::1]'].includes(url.hostname) ||
      url.username || url.password || url.search || url.hash) throw Error('Expected literal loopback gateway URL');
  if (!model || !/^[\w./-]+$/.test(model)) throw Error('Missing gateway model');
  url.pathname=url.pathname.replace(/\/$/,'').replace(/\/responses$/,'')+'/responses';
  return async function* generate({payload,stream,signal}) {
    const bytes=Buffer.from(JSON.stringify(responseRequest(payload,model,stream)));
    const client=url.protocol==='http:'?http:https;
    const headers={'content-type':'application/json','content-length':bytes.length,
      accept:stream?'text/event-stream':'application/json'};
    if (apiKey) headers.authorization='Bearer '+apiKey;
    const body=await new Promise((resolve,reject)=>{
      const req=client.request(url,{method:'POST',headers,signal,agent:false},resolve);
      req.once('error',reject);
      req.setTimeout(180000,()=>req.destroy(Error('Local gateway timed out')));
      req.end(bytes);
    });
    const textSeen=new Set(),calls=new Set();
    try {
      if (body.statusCode!==200) throw Object.assign(Error('Local subscription gateway returned HTTP '+body.statusCode),{status:body.statusCode});
      if (!(body.headers['content-type'] ?? '').includes('text/event-stream')) {
        let size=0;const chunks=[];
        for await(const b of body) { size+=b.length;if(size>cap)throw Error('Gateway response too large');chunks.push(b); }
        const r=JSON.parse(Buffer.concat(chunks).toString('utf8'));
        yield chunk(model,outputParts(r.output,textSeen,calls),finish(r),r.usage);
        return;
      }
      for await(const e of events(body)) {
        if (e.type==='response.output_text.delta' || e.type==='response.refusal.delta') {
          textSeen.add(e.item_id);
          if(e.delta) yield chunk(model,[{text:e.delta}]);
        } else if(e.type==='response.output_item.done') {
          const parts=outputParts([e.item],textSeen,calls);
          if(parts.length) yield chunk(model,parts);
        } else if(e.type==='response.completed' || e.type==='response.incomplete') {
          yield chunk(model,outputParts(e.response.output,textSeen,calls),finish(e.response),e.response.usage);
          return;
        } else if(e.type==='error' || e.type==='response.failed') throw Error('Local subscription generation failed');
      }
      throw Error('Local gateway stream ended without a response status');
    } finally { body.destroy(); }
  };
}
