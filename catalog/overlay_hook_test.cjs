const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {hook,history,status,group,before,after} = JSON.parse(fs.readFileSync(0,'utf8'));
function checkEffortSubmenu(){
  const input=['high','max','low','medium','xhigh'];
  const canonical=['low','medium','high','xhigh','max'];
  const labels={low:'Low',medium:'Medium',high:'High',xhigh:'Extra High',max:'Max',minimal:'Minimal',adaptive:'Adaptive',ultra:'Ultra'};
  const components=Object.fromEntries(['rW','sW','G5','jW','jJ','rx','mW','nW','kW'].map(name=>[name,name]));
  function render(family,branch,withContext,published=input){
    const options=published.map((level,i)=>({modelId:family+'-'+level,label:family+' ('+labels[level]+')',value:1000+i}));
    const groups={[family]:{displayName:'Example',defaultThinkingSuffix:'medium',
      supportedThinkingLevels:published.map(effort=>({thinkingSuffix:effort,thinkingDisplayName:labels[effort]}))}};
    let choice;
    const script=group+'\nconst f=lVb(options,groups); (function(){'+branch+'})()';
    const result=vm.runInNewContext(script,{...components,options,groups,a:options[0],c:options[3],
      O:false,N:false,F:'test',n:withContext,D:'context-option',hYb:()=>true,b:option=>{choice=option},
      E:{createElement:(kind,props,...children)=>({kind,props,children:children.flat()})}});
    const nodes=[];
    function walk(el){if(!el||typeof el!=='object')return;nodes.push(el);el.children.forEach(walk)}
    walk(result);
    const effortRows=nodes.filter(el=>el.props?.['data-testid']==='model-selector-effort-option');
    const rows=effortRows.map(el=>el.props['data-effort']);
    for(const row of effortRows)assert.equal(row.children[0],labels[row.props['data-effort']]);
    if(withContext)nodes.find(el=>el.kind==='kW'&&el.props.key==='xhigh').props.onClick();
    else{
      const menu=nodes.find(el=>el.kind==='mW');
      assert.equal(menu.props.value,'medium');
      menu.props.onValueChange('xhigh');
    }
    assert.equal(choice,options.find(option=>option.modelId.endsWith('-xhigh')));
    return rows;
  }
  for(const mode of [false,true]) {
    for(const family of ['codex-gpt-6.2-sol','codex-gpt-6.2-astra']){
      assert.deepEqual(render(family,before,mode),input);
      assert.deepEqual(render(family,after,mode),canonical);
    }
    for(const family of ['gemini-native','gpt-oss-120b'])
      assert.deepEqual(render(family,after,mode),render(family,before,mode));
    assert.deepEqual(render('codex-gpt-6.2-test',after,mode,[...input,'adaptive','ultra','minimal']),
      ['minimal',...canonical,'adaptive']);
  }
}
async function test(){
  checkEffortSubmenu();
  let fn,cleanup,previousConfig,button,expired=false;
  let auth = {state:'signedIn'};
  const replies=[], timers=new Map(), dispatches=[],state={userStatus:{email:'sample@example.invalid'},modelSelection:{}};
  const slug='codex-gpt-6.2-sol-medium',native={modelId:'gemini',value:4,label:'Gemini'};
  const restored={modelId:slug,value:72,label:'GPT-6.2 Sol (Medium)'};
  const scope={
    e: value => value, hl:()=>auth,m:false,b:'cid',n:{},y:false,B:native,uA:{},G:{Model:{UNSPECIFIED:0}},
    vl:()=>previousConfig,ul:select=>select(state),nm:()=>({stepCount:4}),RB:()=>scope.options,options:[native],
    E:{useEffect(cb){fn=cb},useContext(){return agent},useState(){return [expired,next=>{expired=next}]}},
    D:{getState(){return state},dispatch(x){dispatches.push(x)}},
    bk: () => new Map(), V3b: value => Boolean(value?.email), Z_a: () => undefined, $_a: () => undefined,
    ara:value=>value, ZB:value=>value, console, vh:class extends Error{},
    setTimeout(cb,ms){const timer=()=>cb();timers.set(timer,ms);return timer},clearTimeout(timer){timers.delete(timer)}
  };
  const agent={getUserStatus(){return new Promise(resolve=>replies.push(resolve))}};
  vm.createContext(scope);vm.runInContext(history+'\n'+status,scope);
  const script=new vm.Script('(()=>{'+hook+';return catalogButton})()');
  const render=()=>{cleanup?.();button=script.runInContext(scope);cleanup=fn()};
  const finish=async(i,name)=>{replies[i]({userStatus:{email:'sample@example.invalid',name}});await new Promise(r=>setImmediate(r))};
  render();assert.equal(replies.length,0);
  scope.m=true;render();assert.equal(replies.length,1);assert.equal(timers.size,1);
  for(const cb of [...timers.keys()])cb();
  await finish(1,'newer');await finish(0,'old');assert.deepEqual(dispatches.map(x=>x.name),['newer']);
  scope.m=false;render();assert.equal(timers.size,0);
  scope.m=true;render();scope.m=false;render();await finish(2,'closed');assert.equal(dispatches.length,1);
  scope.m=true;render();auth={state:'signedIn'};await finish(3,'other account');assert.equal(dispatches.length,1);
  scope.m=false;render();scope.m=true;auth={state:'signedOut'};render();assert.equal(replies.length,4);assert.equal(timers.size,0);
  auth={state:'signedIn'};scope.m=false;
  previousConfig={modelName:slug,planModel:18};render();
  assert.equal(replies.length,5,'restoring a subscription fetches immediately with the picker closed');
  assert.match(button.label,/恢复/);assert.equal(timers.size,7);
  const cfg={plannerConfig:{planModel:72}},row={plannerConfig:previousConfig};
  const source={trajectorySlice:{generatorMetadatasInSlice:[row],totalStepsLength:4,totalGeneratorMetadataLength:1}};
  const guard=(chosen,request)=>scope.agResumeGuard(source,state,'cid',chosen,request);
  assert.throws(()=>guard(native,{plannerConfig:{planModel:4}}),/订阅模型/);
  assert.throws(()=>scope.agResumeGuard(undefined,state,'cid',native,cfg),/历史/);
  const sameOldSlot={modelId:'vendor-native',label:'Native slot',modelOrAlias:{choice:{case:'model',value:18}}};
  const moved={modelId:slug,label:restored.label,modelOrAlias:{choice:{case:'model',value:72}}};
  assert.equal(scope.chc(source,[sameOldSlot,moved],row).modelLabel,restored.label);
  assert.equal(scope.chc(source,[sameOldSlot],row).modelLabel,undefined);
  scope.options=[native,restored];scope.B=restored;render();
  assert.equal(button,restored);assert.equal(timers.size,0);
  assert.doesNotThrow(()=>guard(restored,cfg));
  assert.throws(()=>guard(restored,{plannerConfig:{planModel:18}}),/订阅模型/,'stale slot');
  const beforeNative=replies.length;
  state.modelSelection={trajectorySync:{cid:{pick:{atStep:4}}},byConversation:{cid:{model:4}}};
  scope.B=native;render();assert.equal(button,native);assert.equal(replies.length,beforeNative);
  assert.doesNotThrow(()=>guard(native,{plannerConfig:{planModel:4}}));
  state.modelSelection.byConversation.cid={model:72,customLabel:slug};scope.options=[native];
  assert.throws(()=>guard(native,{plannerConfig:{planModel:4}}),/订阅模型/);
  previousConfig={modelName:'gemini',planModel:4};state.modelSelection={};render();
  assert.equal(replies.length,beforeNative);assert.equal(timers.size,0);
  assert.doesNotThrow(()=>scope.agResumeGuard({trajectorySlice:{generatorMetadatasInSlice:[{plannerConfig:previousConfig}]}},state,'cid',native,{plannerConfig:{planModel:4}}));
  const nativeHistory={totalStepsLength:4,totalGeneratorMetadataLength:1,generatorMetadatasInSlice:[{metadata:{case:'chatModel',value:{model:4}}}]};
  assert.doesNotThrow(()=>scope.agResumeGuard({trajectorySlice:nativeHistory},state,'cid',native,{plannerConfig:{planModel:4}}));
  assert.equal(scope.agResumeSlug('ag-codex-8-invalid-medium'),undefined);
  assert.equal(scope.agResumeSlug('ag-codex-11-gpt-6.2-sol-medium'),'codex-gpt-6.2-sol-medium');
  assert.equal(scope.agResumeSlug('codex-gpt-6.2-astra-xhigh'),'codex-gpt-6.2-astra-xhigh');
  assert.equal(scope.agResumeSlug('codex-invalid'),undefined);
  assert.equal(scope.agResumeSlug('gpt-oss-120b-medium'),undefined);
}
test().catch(e=>{console.error(e);process.exitCode=1});
