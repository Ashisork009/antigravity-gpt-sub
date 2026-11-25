"""Reconcile a managed collaboration Skill after a successful deployment change."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from uuid import uuid4

SKILL_SLUG = 'gpt-swarm-workflow'
MARKER_FILE = '.managed-by-antigravity-gpt-sub.json'
PREFERENCE_FILE = 'collaboration-skill.json'
OWNER = 'antigravity-gpt-sub'
LANGUAGES = ('zh', 'en')


def _entry(path, kind):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not kind(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError(f'Not a direct filesystem entry: {path}')
    return True


def _directory(path):
    return all(_entry(part, stat.S_ISDIR) for part in (*reversed(path.parents), path))


def _bytes(path):
    if not _entry(path, stat.S_ISREG):
        raise FileNotFoundError(path)
    return path.read_bytes()


def _json(path):
    return json.loads(_bytes(path).decode('utf-8'))


def _files(value):
    if not isinstance(value, dict) or 'SKILL.md' not in value or any(
        not (name == 'SKILL.md' or re.fullmatch(r'references/[^/\\:*?"<>|\x00-\x1f]+\.md', name))
        or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
        for name, digest in value.items()
    ) or len({os.path.normcase(name) for name in value}) != len(value):
        raise ValueError('Invalid Skill file list')
    return value


def _verified(path, digest):
    data = _bytes(path)
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f'Skill file hash mismatch: {path}')
    return data


def _owned(target):
    if not _directory(target):
        return None
    marker = _json(target / MARKER_FILE)
    if (not isinstance(marker, dict) or type(marker.get('schema')) is not int or marker['schema'] != 1
            or marker.get('owner') != OWNER or marker.get('slug') != SKILL_SLUG
            or marker.get('language') not in LANGUAGES
            or not isinstance(marker.get('templateVersion'), str) or not marker['templateVersion']):
        raise ValueError('Missing or unrecognized Skill ownership marker')
    files = _files(marker.get('files'))
    refs = {name.split('/')[1] for name in files if name.startswith('references/')}
    expected = {'SKILL.md', MARKER_FILE} | ({'references'} if refs else set())
    if {entry.name for entry in target.iterdir()} != expected or (refs and (
        not _directory(target / 'references') or {p.name for p in (target / 'references').iterdir()} != refs
    )):
        raise ValueError('Unexpected Skill files or directories')
    for name, digest in files.items():
        _verified(target / name, digest)
    return marker


def _save(path, value):
    with path.open('xb') as output:
        output.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8'))


def _refresh(stage, templates, manifest_path, language):
    manifest = _json(manifest_path)
    if (not isinstance(manifest, dict) or type(manifest.get('schema')) is not int or manifest['schema'] != 1
            or manifest.get('slug') != SKILL_SLUG
            or not isinstance(manifest.get('version'), str) or not manifest['version']):
        raise ValueError('Invalid bundled Skill manifest')
    try:
        language_files = {lang: _files(manifest['languages'][lang]['files']) for lang in LANGUAGES}
    except (KeyError, TypeError) as exc:
        raise ValueError('Invalid bundled Skill languages') from exc
    files = language_files[language]
    stage.mkdir()
    for name, digest in files.items():
        source = templates / language / name
        if not _directory(source.parent):
            raise FileNotFoundError(source.parent)
        prepared = stage / name
        prepared.parent.mkdir(exist_ok=True)
        data = _verified(source, digest)
        with prepared.open('xb') as output:
            output.write(data)
    _save(stage / MARKER_FILE, dict(schema=1, owner=OWNER, slug=SKILL_SLUG,
                                   language=language, templateVersion=manifest['version'], files=files))


def _preferences(path):
    if not _directory(path.parent) or not _entry(path, stat.S_ISREG):
        return {'version': 1, 'enabled': False, 'language': 'zh'}
    pref = _json(path)
    if (not isinstance(pref, dict) or type(pref.get('version')) is not int or pref['version'] != 1
            or type(pref.get('enabled')) is not bool or pref.get('language') not in LANGUAGES):
        raise ValueError('Invalid collaboration Skill preferences')
    return pref


def reconcile_skill(action, store_dir, config_dir, templates_dir=None):
    """Refresh or remove only an exact, unmodified managed Skill tree."""
    if action not in ('upgrade', 'uninstall', 'rollback'):
        raise ValueError(f'Unknown Skill lifecycle action: {action}')
    config = Path(config_dir).absolute()
    target = config / 'skills' / SKILL_SLUG
    conflict = {'state': 'preserved_conflict', 'warning': f'Preserved a custom or modified Skill at {target}.'}
    try:
        installed = _owned(target)
    except (OSError, ValueError):
        return conflict

    templates = Path(templates_dir).absolute() if templates_dir is not None else None
    manifest = templates / 'manifest.json' if templates is not None else None

    def has_manifest():
        return manifest is not None and _directory(templates) and _entry(manifest, stat.S_ISREG)

    remove = action == 'uninstall' or (action == 'rollback' and not has_manifest())
    if remove and installed is None:
        return {'state': 'absent'}

    pref_path = Path(store_dir).absolute() / PREFERENCE_FILE
    warning = None
    try:
        pref = _preferences(pref_path)
    except (OSError, ValueError):
        if not remove:
            raise
        pref = None
        warning = f'Preserved unreadable or invalid Skill preferences at {pref_path}.'
    if not remove and not pref['enabled']:
        return {'state': 'disabled'}
    if installed is None:
        return {'state': 'absent'}
    if action == 'upgrade' and not has_manifest():
        return {'state': 'unsupported'}

    suffix = uuid4().hex
    stage = config / ('.gpt-sub-skill-stage-' + suffix)
    backup = config / ('.gpt-sub-skill-old-' + suffix)
    disable_pref = remove and pref is not None and pref['enabled']
    pending_pref = pref_path.with_name(pref_path.name + '.' + suffix + '.tmp')
    try:
        if not remove:
            _refresh(stage, templates, manifest, pref['language'])
        elif disable_pref:
            _save(pending_pref, dict(pref, enabled=False))
        try:
            if _owned(target) != installed:
                return conflict
        except (OSError, ValueError):
            return conflict
        target.rename(backup)
        try:
            unchanged = _owned(backup) == installed
        except (OSError, ValueError):
            unchanged = False
        if not unchanged:
            backup.rename(target)
            return conflict
        try:
            if not remove:
                stage.rename(target)
            elif disable_pref:
                pending_pref.replace(pref_path)
        except OSError:
            backup.rename(target)
            raise
        shutil.rmtree(backup)
    finally:
        if stage.is_dir():
            shutil.rmtree(stage)
        if disable_pref:
            pending_pref.unlink(missing_ok=True)
    result = {'state': 'removed' if remove else 'synced'}
    if warning:
        result['warning'] = warning
    return result
