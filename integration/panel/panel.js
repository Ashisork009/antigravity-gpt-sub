'use strict';
const $=id=>document.getElementById(id);
const defaultModels=['gpt-6.2-sol','gpt-6.2-astra'];
const defaultEfforts=['low','medium','high','xhigh','max'];
const labels={low:'Low',medium:'Medium',high:'High',xhigh:'Extra High',max:'Max'};
const modelLabels={'gpt-6.2-sol':'GPT-6.2 Sol','gpt-6.2-astra':'GPT-6.2 Astra'};
let state,latest='',busy=false,loading=false,queuedUntil=0,refreshUntil=0,gen=0,serverNotice=false;
const transientErrors=new Set(['catalog_unavailable','catalog_timeout']);
function notice(text,fromServer=false){$('notice').textContent=text;$('notice').hidden=!text;serverNotice=fromServer&&!!text;}
async function call(path,data={}){
  const r=await window.sidecar.fetch(path,{method:'POST',body:JSON.stringify(data)});
  const json=await r.json();if(!r.ok)throw Object.assign(Error(json.error||'请求失败'),{status:r.status});return json;
}
const unique=list=>[...new Set(list)];
function row(parent,group,value,selected,detail) {
  const label=document.createElement('label');label.className='row';
  const input=document.createElement('input');input.type='checkbox';input.value=value;input.dataset.group=group;
  input.checked=selected;input.disabled=busy;input.addEventListener('change',()=>void update(group,value,input.checked));
  const span=document.createElement('span');const name=document.createElement('span');
  if(group==='models'){
    name.textContent=modelLabels[value]??state.models.find(row=>row.id===value)?.title??value;name.className='model-name';label.title=value;
  }else{name.textContent=labels[value]??value;}
  span.append(name);
  if(detail){const small=document.createElement('small');small.textContent=detail;span.append(small);}
  label.append(input,span);parent.append(label);
}
const skillLanguages={zh:'中文',en:'English'};
function skillNotice(text){$('skill-error').textContent=text;$('skill-error').hidden=!text;}
function renderSkill(skill){
  const enabled=$('skill-enabled'),language=$('skill-language'),sync=$('skill-sync');
  const available=!!skill&&!skill.error,residual=skill?.status==='active'&&!skill.enabled;
  const disabled=busy||!available||skill?.status==='conflict';
  enabled.checked=!!skill?.enabled||residual;enabled.disabled=disabled;
  language.value=skill?.language??'zh';language.disabled=disabled||residual;
  sync.hidden=!['outdated','missing'].includes(skill?.status);sync.disabled=disabled;
  const installed=available?`${skillLanguages[skill.installedLanguage]} · ${skill.installedVersion==='dev'?'dev':'v'+skill.installedVersion}`:'';
  const messages={off:'默认关闭，开启后挂载至全局 Skill（下一轮对话生效）。',
    active:residual?`全局 Skill 仍已挂载（${installed}），关闭开关可清理。`:`已启用（${installed}），下一轮对话生效。`,
    outdated:'已安装的模板版本或语言不一致，点击同步更新。',missing:'全局 Skill 目录缺失，点击重新写入。',
    conflict:'检测到同名自定义或已修改的 Skill 目录，已保护未覆盖，请先手动处理。'};
  $('skill-status').textContent=messages[skill?.status]??'暂时无法读取 Skill 设置。';
}
async function updateSkill(changes){
  const skill=state?.skill;
  if(busy||!skill?.stamp)return;
  ++gen;busy=true;render(state);skillNotice('');
  try{state=await call('/api/skill',{stamp:skill.stamp,enabled:skill.enabled,language:skill.language,...changes});}
  catch(e){skillNotice(e.message==='skill_directory_conflict'?'目录有冲突，未保存任何更改。':
    e.message==='skill_changed'?'Skill 状态已变化，已重新读取。':'无法保存 Skill 设置，请重试。');}
  finally{busy=false;latest='';render(state);await refresh();}
}
function render(s){
  state=s;
  const now=Date.now(),refreshing=Boolean(s.refreshing)||now<refreshUntil;
  const sKey=JSON.stringify([s,busy,now<queuedUntil,refreshing]);if(latest===sKey)return;latest=sKey;
  renderSkill(s.skill);
  const wait=s.pending||now<queuedUntil;
  const transient=s.connected&&transientErrors.has(s.error);
  $('connection').textContent=s.fixture?'确定性测试模型已连接':wait?'等待系统浏览器完成订阅授权':s.connected?'使用已授权的 ChatGPT 订阅':
    s.error==='gateway_starting'?'正在连接宿主网关':'连接 ChatGPT 后可读取当前订阅支持的模型和等级。';
  const showSignin=!s.fixture&&!wait&&(!s.connected||(s.error&&s.error!=='gateway_starting'&&!transient));
  const showRefresh=!s.fixture&&!wait&&s.connected;
  $('signin').hidden=!showSignin;$('signin').disabled=busy||wait||s.error==='gateway_starting';
  $('refresh').hidden=!showRefresh;$('refresh').disabled=busy||refreshing||s.error==='gateway_starting';
  $('refresh').textContent=refreshing?'正在刷新…':'刷新目录';
  $('conn-actions').hidden=!showSignin&&!showRefresh;
  if(s.error&&s.error!=='gateway_starting'){
    notice(transient&&s.models.length?'网络波动，正在后台重试刷新目录（已保留上次模型列表）：'+s.error:'连接状态：'+s.error,true);
  }else if(serverNotice){notice('');}
  const models=unique([...s.models.map(r=>r.id),...defaultModels,...s.prefs.models]);
  const efforts=unique([...defaultEfforts,...s.models.flatMap(r=>r.efforts),...s.prefs.efforts]);
  $('models').replaceChildren();$('efforts').replaceChildren();
  let combinations=0;
  for(const id of models){
    const r=s.models.find(m=>m.id===id),on=s.prefs.models.includes(id);
    const info=r?(r.efforts.length?'':'目录未提供可选推理等级'):(s.connected?'当前订阅目录未列出':'授权后核对可用性');
    row($('models'),'models',id,on,info);
    if(on&&r)combinations+=s.prefs.efforts.filter(e=>r.efforts.includes(e)).length;
  }
  const active=s.models.filter(r=>s.prefs.models.includes(r.id));
  for(const e of efforts){
    const unsupported=active.filter(m=>!m.efforts.includes(e)).map(m=>m.id);
    row($('efforts'),'efforts',e,s.prefs.efforts.includes(e),unsupported.length?'不适用于 '+unsupported.join('、'):'');
  }
  for(const group of ['models','efforts'])$(group+'-none').disabled=busy||!s.prefs[group].length;
  $('selection-summary').textContent=s.connected||s.fixture?'当前选择可显示 '+combinations+' 个模型与等级组合。':'选择将保存在本机。';
}
async function refresh(){
  if(loading||busy)return;loading=true;
  const g=gen;
  try{const s=await call('/api/state');if(!busy&&g===gen)render(s);}
  catch{if(!busy&&g===gen)notice('暂时无法读取设置，正在等待宿主。');}finally{loading=false;}
}
async function update(group,value,checked){
  if(busy||!state)return;
  const prefs={...state.prefs};
  prefs[group]=value===null?[]:checked?unique([...prefs[group],value]):prefs[group].filter(x=>x!==value);
  ++gen;busy=true;render(state);
  try{const next=await call('/api/model-preferences',{stamp:state.stamp,prefs});notice('');state=next;}
  catch(e){notice(e.status===409?'其他窗口已修改设置，已重新读取。':'保存失败，请重新选择。');}
  finally{busy=false;latest='';render(state);await refresh();}
}
$('signin').addEventListener('click',async()=>{
  try{busy=true;render(state);await call('/api/signin');queuedUntil=Date.now()+1300;notice('');}
  catch{notice('无法发起授权，请检查插件是否已启用。');}
  finally{busy=false;render(state);}
});
$('refresh').addEventListener('click',async()=>{
  try{busy=true;render(state);await call('/api/refresh');refreshUntil=Date.now()+1500;if(serverNotice)notice('');}
  catch{notice('无法刷新目录，请检查订阅连接状态。');}
  finally{busy=false;latest='';render(state);await refresh();}
});
for(const g of ['models','efforts'])$(g+'-none').addEventListener('click',()=>void update(g,null,false));
$('skill-enabled').addEventListener('change',e=>void updateSkill({enabled:e.target.checked}));
$('skill-language').addEventListener('change',e=>void updateSkill({language:e.target.value}));
$('skill-sync').addEventListener('click',()=>void updateSkill({sync:true}));
void refresh();setInterval(refresh,700);

