"""Manage a locally generated, hash-addressed renderer overlay across desktop migrations."""
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

import core_manage as core
from renderer_overlay import ensure_overlay


class OverlayStore:
    def __init__(self, store, language_server, release):
        self.root = core.direct(store / 'overlays')
        self.language_server = core.direct(language_server)
        self.host = release['host']
        self.active_path = core.direct(self.root / 'active.json')
        self.digest = None

    def paths(self, digest):
        core.require(isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest), 'Invalid renderer digest')
        return core.direct(self.root / (digest + '.zip')), core.direct(self.root / (digest + '.owned.json'))

    @staticmethod
    def ownership(marker, digest):
        if not marker.exists():
            return False
        core.require(json.loads(marker.read_bytes()) == {'sha256': digest, 'type': 'local-renderer-overlay'}, 'Renderer ownership record changed')
        return True

    @staticmethod
    def mark(marker, digest):
        if not OverlayStore.ownership(marker, digest):
            core.publish_file(marker, json.dumps({'sha256': digest, 'type': 'local-renderer-overlay'}).encode())

    def set_active(self, digest):
        core.direct(self.active_path)
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.active_path.with_name(self.active_path.name + '.' + uuid4().hex + '.tmp')
        try:
            with tmp.open('xb') as f:
                f.write(json.dumps({'sha256': digest, 'host': self.host}, sort_keys=True).encode())
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.active_path)
        finally:
            tmp.unlink(missing_ok=True)
        self.digest = digest

    def clear_active(self):
        if self.active_path.exists():
            core.direct(self.active_path).unlink()

    def ensure(self):
        self.root.mkdir(parents=True, exist_ok=True)
        result = ensure_overlay(self.language_server, self.root)
        path, marker = self.paths(result)
        core.require(path.is_file() and core.file_hash(path) == result, 'Generated renderer digest differs')
        self.ownership(marker, result)
        self.mark(marker, result)
        self.set_active(result)
        return result

    def verify(self, digest):
        path, marker = self.paths(digest)
        core.require(path.is_file() and core.file_hash(path) == digest, 'Close the desktop and run install to restore its renderer overlay')
        self.ownership(marker, digest)
        core.require(self.active_path.is_file() and json.loads(self.active_path.read_bytes()).get('sha256') == digest,
                     'Close the desktop and run install to restore its renderer overlay')
        self.digest = digest

    def snapshot(self, digest, directory):
        if not digest:
            return None
        path, marker = self.paths(digest)
        if not path.exists():
            return {'sha256': digest, 'present': False, 'owned': self.ownership(marker, digest)}
        core.require(core.file_hash(path) == digest, 'Keeping modified renderer overlay')
        backup = core.direct(directory / 'renderer.zip')
        shutil.copyfile(path, backup)
        core.require(core.file_hash(backup) == digest, 'Renderer snapshot changed')
        return {'sha256': digest, 'present': True, 'owned': self.ownership(marker, digest)}

    def restore(self, state, directory):
        if not state:
            self.clear_active()
            return
        digest = state['sha256']
        path, marker = self.paths(digest)
        self.root.mkdir(parents=True, exist_ok=True)
        if state['present']:
            backup = core.direct(directory / 'renderer.zip')
            core.require(core.file_hash(backup) == digest, 'Renderer rollback copy has changed')
            if not path.exists():
                core.publish_file(path, backup.read_bytes())
            core.require(core.file_hash(path) == digest, 'Keeping changed renderer during rollback')
            self.set_active(digest)
        if state['owned']:
            self.mark(marker, digest)

    def retire(self, digest, successor=None):
        if successor is None:
            self.clear_active()
        if not digest or digest == successor:
            return
        path, marker = self.paths(digest)
        if not self.ownership(marker, digest):
            return
        if path.exists():
            core.require(core.file_hash(path) == digest, 'Keeping changed renderer overlay')
            dest = core.direct(self.root.parent / 'removed' / uuid4().hex)
            dest.mkdir(parents=True)
            path.rename(dest / path.name)
        marker.unlink()
