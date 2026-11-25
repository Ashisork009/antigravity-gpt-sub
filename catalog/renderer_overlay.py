"""Build the version-pinned web_bundle_path ZIP from this installation's public UI assets."""
import hashlib
import io
import os
from pathlib import Path
import tempfile
import zipfile

LS_SHA = "73ce9a2405b455a93d1f13db2ae555da50406110217a349b6dd85c377fbdb9d1"
ZIP_START, ZIP_LENGTH = 182614461, 6163915
ZIP_SHA = "2ff079fc95b3ea37765fb42c830d4d4a84fb98f192b44ab3ba66e97ca68ff614"
MAIN_SHA = "f039eca519f153aeac9a0f1d10abc7afd8ff4b8009ef78d684669a3c7955f54d"
EXPECTED_OVERLAY_SHA256 = "5570dd7fc93f14bc26954e2242cafaaa1ebf91bb7cda8c9054d5a1f0aa42b61b"
ANCHOR = b"l=P.isModelSelectorOpen;var R=P.setIsModelSelectorOpen;P=X3b();"
EFFORT_ANCHOR = b"var Q=nVb(a,f);"
HELPER_ANCHOR = b"function bhc(a,b,c=ahc(a?.trajectorySlice?.generatorMetadatasInSlice),d=!1)"
RESOLVE_ANCHOR = b"a=b?.find(k=>{var l=k.modelOrAlias;return l?g!==void 0?"
LABEL_ANCHOR = b"E.createElement(Udd,{placement:a,selectedModel:C,setSelectedModel:J"
SEND_ANCHOR = b"ya=nm(ka,oa.cascadeId);l&&A&&!ta&&xa===oa.cascadeId"
PICK_ANCHOR = b"customLabel:oa.isCustom?oa.label:void 0,contextWindow:ba,pick:"
HELPERS = """
function agResumeSlug(value){
  if(typeof value!=="string")return;
  const legacy=/^ag-codex-([1-9][0-9]{0,2})-([a-z0-9._-]+)$/.exec(value);
  if(legacy){
    const rest=legacy[2],n=Number(legacy[1]);
    if(n<=120&&rest[n]==="-"&&/^[a-z0-9][a-z0-9._-]*$/.test(rest.slice(0,n))&&/^[a-z0-9][a-z0-9_-]*$/.test(rest.slice(n+1)))
      return "codex-"+rest.slice(0,n)+"-"+rest.slice(n+1);
    return;
  }
  const match=/^codex-([a-z0-9][a-z0-9._-]*)$/.exec(value);
  if(match&&match[1].length<=151&&match[1].includes("-"))return value;
}
function agResumeMetadata(agent){
  return ahc(agent?.trajectorySlice?.generatorMetadatasInSlice)?.plannerConfig;
}
function agResumeExpected(metadata,state,cid){
  if(!cid)return;
  const selection=state.modelSelection,chosen=selection?.byConversation?.[cid];
  if(selection?.trajectorySync?.[cid]?.pick)return agResumeSlug(chosen?.customLabel);
  return agResumeSlug(metadata?.modelName);
}
function agResumeGuard(agent,state,cid,choice,config){
  const slice=agent?.trajectorySlice,latest=ahc(slice?.generatorMetadatasInSlice);
  if(!state.modelSelection?.trajectorySync?.[cid]?.pick&&nm(state,cid)?.stepCount>1&&
     !latest&&(!slice?.totalStepsLength||slice.totalGeneratorMetadataLength>0))
    throw Error("会话历史仍在加载。可在载入后重试，输入内容已保留。");
  const expected=agResumeExpected(latest?.plannerConfig,state,cid);
  if(!expected)return;
  const option=SB(state).find(row=>row.modelId===expected&&!row.disabled);
  if(!option||choice?.modelId!==expected||config?.plannerConfig?.planModel!==option.value)
    throw Error("已选订阅模型尚不可用，输入内容已保留。请等待模型恢复，或在模型菜单中明确另选模型。");
}
""".encode()
# The native composer maps Q.efforts directly to submenu rows. Only reorder our
# own namespace, keeping the host's original byEffort map and selected enum.
EFFORT_HOOK = b"""
if(Q){
  const family=VV(a,f);
  if(typeof family==="string"&&/^codex-[a-z0-9][a-z0-9._-]*$/.test(family)&&a.modelId?.startsWith(family+"-")){
    const order=["none","minimal",...dVb],visible=Q.efforts.filter(effort=>effort.toLowerCase()!=="ultra");
    Q={...Q,efforts:[...order.filter(effort=>visible.includes(effort)),...visible.filter(effort=>!order.includes(effort))]};
  }
}
"""
# Xdd is the original native model button. F is its existing Redux store.
# V3b updates model state through the native service and default filtering.
HOOK = """
const catalogService=(0,E.useContext)(vA),catalogGeminiOnly=Zj().get("models")?.geminiModelsOnly===true;
const catalogMetadata=wl(m,{selector:agResumeMetadata});
const catalogExpected=vl(state=>x?void 0:agResumeExpected(catalogMetadata,state,b));
const catalogMissing=catalogExpected&&C?.modelId!==catalogExpected?catalogExpected:void 0;
const [catalogExpired,setCatalogExpired]=(0,E.useState)(false);
const catalogButton=catalogMissing?{label:catalogExpired?"已选订阅模型暂不可用":"正在恢复订阅模型"}:C;
(0,E.useEffect)(()=>{
  setCatalogExpired(false);
  if((!l&&!catalogMissing)||!catalogService)return;
  const auth=ll(F.getState());
  if(auth?.state==="signedOut")return;
  let disposed=false,sequence=0;
  const refresh=()=>{
    if(disposed||ll(F.getState())!==auth)return;
    const request=++sequence;
    void V3b({agentService:catalogService,store:F,geminiModelsOnly:catalogGeminiOnly,
      isDisposed:()=>disposed||request!==sequence||ll(F.getState())!==auth,ifFetchFails:"keepStatus"});
  };
  refresh();
  const timers=(catalogMissing?[400,1200,2500,5000,10000,20000]:[2500]).map(delay=>setTimeout(refresh,delay));
  if(catalogMissing)timers.push(setTimeout(()=>{if(!disposed)setCatalogExpired(true)},24000));
  return ()=>{disposed=true;timers.forEach(clearTimeout)};
},[l,b,catalogMissing,catalogService,catalogGeminiOnly,F]);
""".encode()

def digest(data):
    return hashlib.sha256(data).hexdigest()

def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()

def require(ok, message):
    if not ok:
        raise ValueError(message)

def original_bundle(language_server):
    with Path(language_server).open("rb") as stream:
        require(hashlib.file_digest(stream,"sha256").hexdigest()==LS_SHA,"Unrecognized desktop language server")
        stream.seek(ZIP_START)
        data=stream.read(ZIP_LENGTH)
    require(digest(data)==ZIP_SHA,"Unexpected official web bundle")
    return data

def edit_main(data):
    edits=overlay_edits()
    require(digest(data)==MAIN_SHA and all(data.count(a)==1 for a,_ in edits),"Unexpected native model picker or send path")
    for anchor,replacement in edits:data=data.replace(anchor,replacement)
    return data


def overlay_edits():
    return [
        (HELPER_ANCHOR,HELPERS+HELPER_ANCHOR),
        (RESOLVE_ANCHOR,b"a=agResumeSlug(f)?b?.find(k=>k.modelId===f&&!k.disabled):"+RESOLVE_ANCHOR[2:]),
        (ANCHOR,ANCHOR+HOOK),
        (EFFORT_ANCHOR,EFFORT_ANCHOR+EFFORT_HOOK),
        (LABEL_ANCHOR,LABEL_ANCHOR.replace(b"selectedModel:C",b"selectedModel:catalogButton")),
        (PICK_ANCHOR,PICK_ANCHOR.replace(b":void 0,",b":agResumeSlug(oa.modelId),")),
        (SEND_ANCHOR,SEND_ANCHOR.replace(b";l&&",b";if(b===oa.cascadeId&&!c&&!k&&!ta)agResumeGuard(v(b)?.getState(),ka,b,p,oa.cascadeConfig);l&&")),
    ]

def write_overlay(source, target):
    # ZIP_STORED and normalized headers give identical output across Python/zlib versions.
    with zipfile.ZipFile(io.BytesIO(source)) as original, zipfile.ZipFile(target,"w") as output:
        require(len(original.infolist())==548 and len(set(original.namelist()))==548,"Unexpected bundle members")
        for item in original.infolist():
            data=original.read(item)
            new=zipfile.ZipInfo(item.filename,date_time=(1980,1,1,0,0,0))
            new.create_system=0
            new.external_attr=16 if item.is_dir() else 32
            output.writestr(new,edit_main(data) if item.filename=="main.js" else data)

def ensure_overlay(language_server: Path, target_zip: Path) -> str:
    source=original_bundle(language_server)
    target_zip=Path(target_zip)
    if target_zip.exists():
        require(file_digest(target_zip)==EXPECTED_OVERLAY_SHA256,"Existing UI overlay has unexpected contents")
        return EXPECTED_OVERLAY_SHA256
    target_zip.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=target_zip.parent,suffix=".tmp")
    temp=Path(name)
    try:
        with os.fdopen(fd,"wb") as stream:
            write_overlay(source,stream)
            stream.flush()
            os.fsync(stream.fileno())
        require(file_digest(temp)==EXPECTED_OVERLAY_SHA256,"Unexpected generated UI overlay")
        try:
            os.link(temp,target_zip)
        except FileExistsError:
            require(file_digest(target_zip)==EXPECTED_OVERLAY_SHA256,"Concurrent overlay change")
        return EXPECTED_OVERLAY_SHA256
    finally:
        temp.unlink(missing_ok=True)
