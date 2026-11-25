"""Edit only our one global sidecar enrollment, preserving other config bytes."""
import json
import re
from pathlib import Path

from asar_tools import edit, require
from project_owner import native_enrollment

SIDECAR_ID='native-model-router-switch'
SPACES=re.compile(r'\s*')
DECODER=json.JSONDecoder()


def members(text,start):
    require(text[start]=='{','Expected a native settings object')
    at=SPACES.match(text,start+1).end()
    result={}
    while text[at]!='}':
        key,index=DECODER.raw_decode(text,at)
        colon=SPACES.match(text,index).end()
        require(isinstance(key,str) and key not in result and text[colon]==':','Invalid settings object')
        begin=SPACES.match(text,colon+1).end()
        obj,end=DECODER.raw_decode(text,begin)
        sep=SPACES.match(text,end).end()
        result[key]=(at,begin,end,sep,obj)
        if text[sep]=='}':break
        require(text[sep]==',','Invalid settings separator')
        at=SPACES.match(text,sep+1).end()
    return result


def insert(text,start,key,value):
    extra=',' if members(text,start) else ''
    return text[:start+1]+json.dumps(key)+':'+value+extra+text[start+1:]


def remove(text,start,key):
    rows=members(text,start)
    at,_,end,sep,_=rows[key]
    if text[sep]==',':return text[:at]+text[sep+1:]
    before=list(rows).index(key)
    if before:
        prior=list(rows.values())[before-1][3]
        return text[:prior]+text[end:]
    return text[:at]+text[end:]


def settings(raw):
    bom=b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    text=raw[len(bom):].decode()
    obj=json.loads(text)
    require(isinstance(obj,dict) and isinstance(obj.get('sidecars',{}),dict),'Unknown native settings')
    return bom,text,obj


def enrollment(config):
    _,_,obj=settings(config.read_bytes())
    require(SIDECAR_ID not in obj.get('sidecars',{}),'Existing sidecar settings are not owned by this release')
    return {'sidecars_existed':'sidecars' in obj}


def enable_sidecar(config,receipt,enabled):
    def transform(original):
        bom,text,obj=settings(original)
        start=SPACES.match(text).end()
        root=members(text,start)
        if 'sidecars' not in root:
            if not enabled:return original
            text=insert(text,start,'sidecars','{}')
            root=members(text,start)
        slot=root['sidecars'][1]
        rows=members(text,slot)
        if SIDECAR_ID in rows:
            require(native_enrollment(config,SIDECAR_ID,rows[SIDECAR_ID][4]),'Unknown or customized sidecar setting; retaining it')
            if not enabled:
                text=remove(text,slot,SIDECAR_ID)
                if not receipt['sidecars_existed'] and not members(text,slot):
                    text=remove(text,start,'sidecars')
        elif enabled:
            text=insert(text,slot,SIDECAR_ID,'{"enabled":true}')
        new=bom+text.encode()
        _,_,check=settings(new)
        require(native_enrollment(config,SIDECAR_ID,check.get('sidecars',{}).get(SIDECAR_ID))==enabled,'Sidecar enrollment failed')
        return new
    edit(Path(config),transform)
