"""Recognize a 2.35.1 sidecar project by its official per-project ownership metadata."""
import json
from pathlib import Path
import uuid


def native_enrollment(config,sidecar_id,value):
    if not isinstance(value,dict) or value.get('enabled') is not True:return False
    if set(value)=={'enabled'}:return True
    if set(value)!={'enabled','projectId','schemaVersion'}:return False
    if type(value['schemaVersion']) is not int or value['schemaVersion']!=1:return False
    project_id=value['projectId']
    if not isinstance(project_id,str):return False
    try:
        if str(uuid.UUID(project_id))!=project_id.lower():return False
        metadata=Path(config).parent/'projects'/(project_id+'.json')
        if metadata.resolve()!=metadata.absolute() or not metadata.is_file():return False
        stat=metadata.stat()
        if stat.st_nlink!=1 or stat.st_size>4*1024*1024:return False
        project=json.loads(metadata.read_bytes())
        return (project.get('id')==project_id and project.get('name')==sidecar_id and
                project.get('sidecar')=={'sidecarId':sidecar_id})
    except (AttributeError,OSError,ValueError):
        return False
