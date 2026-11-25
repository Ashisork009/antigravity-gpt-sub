// Included only in the instrumented acceptance build. No account credentials or upstream connection.
import {createServer,request} from 'node:http';
import {once} from 'node:events';
import {randomUUID} from 'node:crypto';
import {appendFileSync} from 'node:fs';
import {join} from 'node:path';
import {Readable} from 'node:stream';
import {setTimeout as delay} from 'node:timers/promises';
import {pathToFileURL} from 'node:url';
import {planRequest} from '../subscription/plan.mjs';

function trialAction(wire,id){
  const last=wire.input.findLast(item=>item.role==='user');
  const text=last?.content?.map(p=>p.text??'').join('\n')??'';
  if(text.includes('AGY_FIXTURE_FAULT'))return {status:503};
  if(text.includes('AGY_FIXTURE_SLOW'))return {slow:true};
  const match=text.match(/AGY_FIXTURE_READ\s+([^\r\n<>"]*?[\\/]sample-project[\\/]wire-marker\.txt)/i);
  const recall=text.includes('AGY_FIXTURE_RECALL');
  if(!match&&!recall)return {};
  const result=wire.input.filter(i=>i.type==='function_call_output').map(i=>JSON.stringify(i.output)).join('\n');
  const learned=result.match(/\bNATIVE_PROBE_[a-f0-9]{32}\b/i)?.[0];
  if(learned)return {text:learned,returnedToolResult:true};
  if(recall)return {text:'No marker in the supplied conversation.'};
  const tool=wire.tools?.flatMap(ns=>ns.tools??[]).find(t=>t.name==='view_file');
  const required=tool?.parameters?.required??[];
  const args={};
  for(const field of Object.keys(tool?.parameters?.properties??{})){
    const name=field.toLowerCase().replaceAll('_','');
    if(['absolutepath','path','filepath','targetfile','fileuri','absoluteuri'].includes(name))
      args[field]=name.endsWith('uri')?pathToFileURL(match[1]).href:match[1];
    else if(required.includes(field)&&['startline','startlinenumber','firstline'].includes(name))args[field]=1;
    else if(required.includes(field)&&['endline','endlinenumber','lastline','limit','numlines'].includes(name))args[field]=20;
  }
  if(!tool||!Object.keys(args).length||!required.every(k=>k in args))return {text:'Unsupported native view_file declaration.'};
  return {call:{type:'function_call',name:tool.name,namespace:'antigravity',call_id:'call_'+id,arguments:JSON.stringify(args)}};
}

export async function openFixture(run){
  const levels=['low','medium','high','xhigh','max','ultra'];
  const rows=['gpt-6.2-sol','gpt-6.2-astra'].map(slug=>({slug,display_name:slug,
    visibility:'list',supported_reasoning_levels:levels.map(effort=>({effort})),default_reasoning_level:'medium'}));
  const endpoint=createServer(async(req,res)=>{
    try{
      if(req.method!=='POST'||req.url!=='/responses'||req.headers.origin)throw Error('bad request');
      let count=0;const chunks=[];
      for await(const chunk of req){count+=chunk.length;if(count>32*1024*1024)throw Error('oversize');chunks.push(chunk);}
      const wire=JSON.parse(Buffer.concat(chunks));
      if(!rows.some(r=>r.slug===wire.model)||!levels.includes(wire.reasoning?.effort))throw Error('invalid selection');
      const id=randomUUID(),action=trialAction(wire,id);
      const record=(file,data)=>appendFileSync(join(run,file),JSON.stringify({time:new Date().toISOString(),id,...data})+'\n');
      record('fixture-wire.jsonl',{model:wire.model,effort:wire.reasoning.effort,accepted:!action.status,status:action.status??200,tool:action.call?.name,returnedToolResult:action.returnedToolResult});
      if(action.status){res.writeHead(action.status);res.end();return;}
      res.writeHead(200,{'content-type':'text/event-stream'});
      const emit=data=>res.write('data: '+JSON.stringify(data)+'\n\n');
      let value=action.text??wire.model+' / '+wire.reasoning.effort;
      if(action.slow){
        let chunks=0;
        res.once('close',()=>record('fixture-stream.jsonl',{chunks,cancelled:!res.writableEnded}));
        value='';
        while(!res.destroyed&&chunks<40){
          const delta='segment '+(++chunks)+'\n';
          emit({type:'response.output_text.delta',item_id:id,delta});value+=delta;
          await delay(350);
        }
        if(res.destroyed)return;
      }else if(!action.call)emit({type:'response.output_text.delta',item_id:id,delta:value});
      const item=action.call??{id,type:'message',content:[{type:'output_text',text:value}]};
      emit({type:'response.completed',response:{status:'completed',output:[item]}});
      res.end();
    }catch{res.writeHead(400);res.end();}
  });
  endpoint.listen(0,'127.0.0.1');await once(endpoint,'listening');
  return {status:async()=>({connected:true,authorizationPending:false}),listModels:async()=>rows,
    respond:({body,signal})=>new Promise((resolve,reject)=>{
      const req=request({host:'127.0.0.1',port:endpoint.address().port,path:'/responses',method:'POST',signal,
        headers:{'content-type':'application/json'}},res=>resolve(new Response(Readable.toWeb(res),{status:res.statusCode,headers:res.headers})));
      req.once('error',reject);req.end(JSON.stringify(planRequest(body)));
    }),close(){endpoint.closeAllConnections();endpoint.close();}};
}
