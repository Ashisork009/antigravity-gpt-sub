"""Build the renderer web_bundle_path ZIP dynamically from this installation's embedded UI assets."""
import hashlib
import io
import os
from pathlib import Path
import struct
import tempfile
import zipfile

ANCHOR = b"m=U.isModelSelectorOpen;var V=U.setIsModelSelectorOpen;U=Hhc();"
EFFORT_ANCHOR = b"var V=L?void 0:ZW(a,f),X=V&&!g?V.efforts:[],"
HELPER_ANCHOR = b"function Hvc(a,b,c=Gvc(a?.trajectorySlice?.generatorMetadatasInSlice),d=!1)"
RESOLVE_ANCHOR = b"a=b?.find(k=>{var l=k.modelOrAlias;return l?g!==void 0?"
LABEL_ANCHOR = b"F.createElement(Ljd,{placement:a,selectedModel:k,setSelectedModel:Q"
SEND_ANCHOR = b"fa=Wo(ta,ia.cascadeId);m&&B&&!ma&&za===ia.cascadeId"
PICK_ANCHOR = b"customLabel:qa.isCustom?qa.label:void 0,contextWindow:ja,pick:"
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
  return Gvc(agent?.trajectorySlice?.generatorMetadatasInSlice)?.plannerConfig;
}
function agResumeExpected(metadata,state,cid){
  if(!cid)return;
  const selection=state.modelSelection,chosen=selection?.byConversation?.[cid];
  if(selection?.trajectorySync?.[cid]?.pick)return agResumeSlug(chosen?.customLabel);
  return agResumeSlug(metadata?.modelName);
}
function agResumeGuard(agent,state,cid,choice,config){
  const slice=agent?.trajectorySlice,latest=Gvc(slice?.generatorMetadatasInSlice);
  if(!state.modelSelection?.trajectorySync?.[cid]?.pick&&Wo(state,cid)?.stepCount>1&&
     !latest&&(!slice?.totalStepsLength||slice.totalGeneratorMetadataLength>0))
    throw Error("会话历史仍在加载。可在载入后重试，输入内容已保留。");
  const expected=agResumeExpected(latest?.plannerConfig,state,cid);
  if(!expected)return;
  const option=ED(state).find(row=>row.modelId===expected&&!row.disabled);
  if(!option||choice?.modelId!==expected||config?.plannerConfig?.planModel!==option.value)
    throw Error("已选订阅模型尚不可用，输入内容已保留。请等待模型恢复，或在模型菜单中明确另选模型。");
}
""".encode()
# The native composer maps V.efforts directly to submenu rows. Only reorder our
# own namespace, keeping the host's original byEffort map and selected enum.
EFFORT_HOOK = b"""
if(V){
  const family=YW(a,f);
  if(typeof family==="string"&&/^codex-[a-z0-9][a-z0-9._-]*$/.test(family)&&a.modelId?.startsWith(family+"-")){
    const order=["none","minimal",...R8b],visible=V.efforts.filter(effort=>effort.toLowerCase()!=="ultra");
    V={...V,efforts:[...order.filter(effort=>visible.includes(effort)),...visible.filter(effort=>!order.includes(effort))]};
  }
}
"""
# Pjd is the original native model button. N is its existing Redux store.
# Fhc updates model state through the native service and default filtering.
HOOK = """
const catalogService=(0,F.useContext)(bC),catalogGeminiOnly=lk().get("models")?.geminiModelsOnly===true;
const catalogMetadata=Cl(n,{selector:agResumeMetadata});
const catalogExpected=Bl(state=>y?void 0:agResumeExpected(catalogMetadata,state,b));
const catalogMissing=!J&&catalogExpected&&k?.modelId!==catalogExpected?catalogExpected:void 0;
const [catalogExpired,setCatalogExpired]=(0,F.useState)(false);
const catalogButton=catalogMissing?{label:catalogExpired?"已选订阅模型暂不可用":"正在恢复订阅模型"}:k;
(0,F.useEffect)(()=>{
  setCatalogExpired(false);
  if((!m&&!catalogMissing)||!catalogService)return;
  const auth=vl(N.getState());
  if(auth?.state==="signedOut")return;
  let disposed=false,sequence=0;
  const refresh=()=>{
    if(disposed||vl(N.getState())!==auth)return;
    const request=++sequence;
    void Fhc({agentService:catalogService,store:N,geminiModelsOnly:catalogGeminiOnly,
      isDisposed:()=>disposed||request!==sequence||vl(N.getState())!==auth,ifFetchFails:"keepStatus"});
  };
  refresh();
  const timers=(catalogMissing?[400,1200,2500,5000,10000,20000]:[2500]).map(delay=>setTimeout(refresh,delay));
  if(catalogMissing)timers.push(setTimeout(()=>{if(!disposed)setCatalogExpired(true)},24000));
  return ()=>{disposed=true;timers.forEach(clearTimeout)};
},[m,b,catalogMissing,catalogService,catalogGeminiOnly,N]);
""".encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def original_bundle(language_server):
    data = Path(language_server).read_bytes()
    pos = len(data)
    found = []
    while True:
        idx = data.rfind(b"PK\x05\x06", 0, pos)
        if idx < 0:
            break
        pos = idx
        if idx + 22 > len(data):
            continue
        disk, cd_disk, _, entries_tot, cd_size, cd_off, com_len = struct.unpack("<HHHHIIH", data[idx + 4 : idx + 22])
        if disk != 0 or cd_disk != 0 or entries_tot < 1 or cd_size < 64 or idx + 22 + com_len > len(data):
            continue
        zip_start = idx - cd_size - cd_off
        zip_end = idx + 22 + com_len
        if zip_start < 0 or data[zip_start : zip_start + 4] != b"PK\x03\x04":
            continue
        chunk = data[zip_start:zip_end]
        try:
            with zipfile.ZipFile(io.BytesIO(chunk)) as zf:
                if "main.js" in zf.namelist():
                    found.append(chunk)
                    if len(found) > 1:
                        break
        except zipfile.BadZipFile:
            continue
    require(len(found) == 1, "Could not locate embedded web bundle in language_server.exe")
    return found[0]


def overlay_edits():
    return [
        (HELPER_ANCHOR, HELPERS + HELPER_ANCHOR),
        (RESOLVE_ANCHOR, b"a=agResumeSlug(f)?b?.find(k=>k.modelId===f&&!k.disabled):" + RESOLVE_ANCHOR[2:]),
        (ANCHOR, ANCHOR + HOOK),
        (EFFORT_ANCHOR, b"var V=L?void 0:ZW(a,f);" + EFFORT_HOOK + b"var X=V&&!g?V.efforts:[]," ),
        (LABEL_ANCHOR, LABEL_ANCHOR.replace(b"selectedModel:k", b"selectedModel:catalogButton")),
        (PICK_ANCHOR, PICK_ANCHOR.replace(b":void 0,", b":agResumeSlug(qa.modelId),")),
        (SEND_ANCHOR, SEND_ANCHOR.replace(b";m&&", b";if(b===ia.cascadeId&&!c&&!k&&!ma)agResumeGuard(w(b)?.getState(),ta,b,q,ia.cascadeConfig);m&&")),
    ]


def edit_main(data):
    edits = overlay_edits()
    require(b"function agResumeSlug(" not in data, "Embedded web bundle is already patched")
    require(all(data.count(a) == 1 for a, _ in edits), "Unexpected native model picker or send path for this Antigravity version")
    for anchor, replacement in edits:
        data = data.replace(anchor, replacement)
    return data


def write_overlay(source, target):
    # ZIP_STORED and normalized headers give identical output across Python/zlib versions.
    with zipfile.ZipFile(io.BytesIO(source)) as original, zipfile.ZipFile(target, "w") as output:
        names = original.namelist()
        require("main.js" in names and len(names) == len(set(names)), "Unexpected bundle members")
        for item in original.infolist():
            data = original.read(item)
            new = zipfile.ZipInfo(item.filename, date_time=(1980, 1, 1, 0, 0, 0))
            new.create_system = 0
            new.external_attr = 16 if item.is_dir() else 32
            output.writestr(new, edit_main(data) if item.filename == "main.js" else data)


def ensure_overlay(language_server: Path, target_dir: Path) -> str:
    source = original_bundle(language_server)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            write_overlay(source, stream)
            stream.flush()
            os.fsync(stream.fileno())
        actual = file_digest(temp)
        target_zip = target_dir / (actual + ".zip")
        if target_zip.exists():
            require(file_digest(target_zip) == actual, "Existing UI overlay has unexpected contents")
            return actual
        try:
            os.link(temp, target_zip)
        except FileExistsError:
            require(file_digest(target_zip) == actual, "Concurrent overlay change")
        return actual
    finally:
        temp.unlink(missing_ok=True)
