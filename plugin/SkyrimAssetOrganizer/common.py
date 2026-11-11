"""Shared mod identity, conservative path checks and sanitized provenance."""
import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Mod:
    name: str
    path: Path
    priority: int
    enabled: bool = True
    separator: bool = False


def _plain(path):
    path=Path(path)
    for component in (path,*path.parents):
        if component.is_symlink() or (component.exists() and getattr(component.stat(follow_symlinks=False),'st_file_attributes',0)&0x400):
            raise ValueError(f'Reparse point is not supported: {component}')


def metadata(path):
    path=Path(path); ini=path/'meta.ini'; _plain(ini)
    parser=configparser.ConfigParser(interpolation=None,strict=False)
    if ini.exists(): parser.read(ini,encoding='utf-8-sig')
    general=dict(parser['General']) if parser.has_section('General') else {}
    result={k:general.get(k,'') for k in ('gamename','modid','version','installationfile','repository')}
    result['installed_files']=dict(parser['installedFiles']) if parser.has_section('installedFiles') else {}
    result['confidence']='mod-level source; archive member unverified' if result['installationfile'] else 'unknown/generated'
    archive=path.parent.parent/'downloads'/Path(result['installationfile']).name
    if result['installationfile'] and archive.is_file(): result['local_download_candidate']=str(archive)
    if result['gamename'].lower()=='skyrimse' and result['modid'].isdigit() and int(result['modid'])>0:
        result['nexus_page']=f"https://www.nexusmods.com/skyrimspecialedition/mods/{result['modid']}"
    return result
