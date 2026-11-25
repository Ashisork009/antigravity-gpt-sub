"""Manage a locally generated, hash-addressed renderer overlay across desktop migrations."""
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

import core_manage as core
from renderer_overlay import EXPECTED_OVERLAY_SHA256, ensure_overlay


class OverlayStore:
    def __init__(self, store, language_server, release):
        self.root=core.direct(store/'overlays')
        self.language_server=core.direct(language_server)
        self.digest=release['web_bundle_sha256']
        core.require(self.digest==EXPECTED_OVERLAY_SHA256,'Renderer generator differs from the release')

    def paths(self,digest):
        core.require(isinstance(digest,str) and re.fullmatch(r'[a-f0-9]{64}',digest),'Invalid renderer digest')
        return core.direct(self.root/(digest+'.zip')),core.direct(self.root/(digest+'.owned.json'))

    @staticmethod
    def ownership(marker,digest):
        if not marker.exists():return False
        core.require(json.loads(marker.read_bytes())=={'sha256':digest,'type':'local-renderer-overlay'},'Renderer ownership record changed')
        return True

    @staticmethod
    def mark(marker,digest):
        if not OverlayStore.ownership(marker,digest):
            core.publish_file(marker,json.dumps({'sha256':digest,'type':'local-renderer-overlay'}).encode())

    def ensure(self):
        path,marker=self.paths(self.digest)
        self.root.mkdir(parents=True,exist_ok=True)
        self.ownership(marker,self.digest)
        if path.exists():
            core.require(core.file_hash(path)==self.digest,'Keeping modified renderer overlay')
            return
        result=ensure_overlay(self.language_server,path)
        core.require(result==self.digest and core.file_hash(path)==self.digest,'Generated renderer digest differs')
        self.mark(marker,self.digest)

    def verify(self):
        path,marker=self.paths(self.digest)
        core.require(path.is_file() and core.file_hash(path)==self.digest,'Close the desktop and run install to restore its renderer overlay')
        self.ownership(marker,self.digest)

    def snapshot(self,digest,directory):
        if not digest:return None
        path,marker=self.paths(digest)
        if not path.exists():
            return {'sha256':digest,'present':False,'owned':self.ownership(marker,digest)}
        core.require(core.file_hash(path)==digest,'Keeping modified renderer overlay')
        backup=core.direct(directory/'renderer.zip')
        shutil.copyfile(path,backup)
        core.require(core.file_hash(backup)==digest,'Renderer snapshot changed')
        return {'sha256':digest,'present':True,'owned':self.ownership(marker,digest)}

    def restore(self,state,directory):
        if not state:return
        digest=state['sha256']
        path,marker=self.paths(digest)
        self.root.mkdir(parents=True,exist_ok=True)
        if state['present']:
            backup=core.direct(directory/'renderer.zip')
            core.require(core.file_hash(backup)==digest,'Renderer rollback copy has changed')
            if not path.exists():core.publish_file(path,backup.read_bytes())
            core.require(core.file_hash(path)==digest,'Keeping changed renderer during rollback')
        if state['owned']:self.mark(marker,digest)

    def retire(self,digest,successor=None):
        if not digest or digest==successor:return
        path,marker=self.paths(digest)
        if not self.ownership(marker,digest):return
        if path.exists():
            core.require(core.file_hash(path)==digest,'Keeping changed renderer overlay')
            dest=core.direct(self.root.parent/'removed'/uuid4().hex)
            dest.mkdir(parents=True)
            path.rename(dest/path.name)
        marker.unlink()
