import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {openFixture} from './fixture.mjs';

test('instrumented endpoint proposes a native file operation and observes upstream cancellation',async()=>{
  const dir=await mkdtemp(join(tmpdir(),'native-model-fixture-'));
  const endpoint=await openFixture(dir);
  const path='E:\\native-fixture\\sample-project\\wire-marker.txt';
  const user=text=>({role:'user',content:[{type:'input_text',text}]});
  const invoke=(input,signal)=>endpoint.respond({signal,body:{input,model:'gpt-6.2-sol',reasoning:{effort:'high'},
    tools:[{type:'function',name:'view_file',parameters:{type:'object',properties:{AbsolutePath:{type:'string'}},required:['AbsolutePath']}}]}});
  try{
    const prompt=user('AGY_FIXTURE_READ '+path);
    const call=(await (await invoke([prompt])).text()).split('\n').filter(s=>s.startsWith('data: ')).map(s=>JSON.parse(s.slice(6))).at(-1).response.output[0];
    assert.equal(call.name,'view_file');assert.deepEqual(JSON.parse(call.arguments),{AbsolutePath:path});
    const marker='NATIVE_PROBE_'+'a'.repeat(32);
    const result={type:'function_call_output',call_id:call.call_id,output:marker};
    assert.ok((await (await invoke([prompt,call,result,user('AGY_FIXTURE_RECALL')])).text()).includes(marker));
    assert.equal((await invoke([user('AGY_FIXTURE_FAULT')])).status,503);
    const control=new AbortController();
    const stream=await invoke([user('AGY_FIXTURE_SLOW')],control.signal);
    const reader=stream.body.getReader();
    assert.equal((await reader.read()).done,false);
    control.abort();await reader.cancel().catch(()=>{});
    await delay(450);
    const info=JSON.parse(await readFile(join(dir,'fixture-stream.jsonl'),'utf8'));
    assert.equal(info.cancelled,true);assert.ok(info.chunks<40);
  }finally{endpoint.close();await rm(dir,{recursive:true,force:true});}
});
