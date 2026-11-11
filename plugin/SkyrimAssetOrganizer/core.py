"""Loose asset planner. Mutation is deliberately restricted to generated testbeds."""
from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Mod:
    name: str
    path: Path
    priority: int
    enabled: bool = True
    separator: bool = False


@dataclass
class Plan:
    mods: list[Mod]
    selected: set[str]
    extensions: set[str]
    actions: list[dict]
    inventory: list[dict]
    output: str = ''
    output_priority: int | None = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    profile: str = 'Selected profile'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _plain(path: Path):
    # Reject junctions as well as symlinks, including ancestor components.
    for component in (path, *path.parents):
        if component.is_symlink() or (component.exists() and
                getattr(component.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400):
            raise ValueError(f'Reparse point is not supported: {component}')


def metadata(path: Path) -> dict:
    ini = path / 'meta.ini'
    _plain(ini)
    if not ini.exists():
        return {'confidence': 'unknown', 'installationFile': '', 'installed_files': []}
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read(ini, encoding='utf-8-sig')
    general = dict(parser['General']) if parser.has_section('General') else {}
    allowed = ('gamename', 'modid', 'version', 'installationfile', 'repository')
    result = {key: general.get(key, '') for key in allowed}
    result['installed_files'] = dict(parser['installedFiles']) if parser.has_section('installedFiles') else {}
    result['confidence'] = 'mod-level source; archive member unverified' if result['installationfile'] else 'unknown/generated'
    archive_name = Path(result['installationfile']).name
    downloads = path.parent.parent / 'downloads'
    if archive_name and (downloads / archive_name).is_file():
        result['local_download_candidate'] = str(downloads / archive_name)
    if result['gamename'].lower() == 'skyrimse' and result['modid'].isdigit() and int(result['modid']) > 0:
        result['nexus_page'] = f"https://www.nexusmods.com/skyrimspecialedition/mods/{result['modid']}"
    return result


def inventory(mods: list[Mod], extensions: set[str]) -> list[dict]:
    records = []
    for mod in sorted(mods, key=lambda item: item.priority):
        if not mod.enabled or mod.separator:
            continue
        root = Path(mod.path).absolute()
        _plain(root)
        if not root.is_dir():
            raise ValueError(f'Mod directory missing: {root}')
        meta = metadata(root)
        seen = set()
        for directory in ('meshes', 'textures'):
            # Windows lookup is insensitive; also support fixture tests on other systems.
            matches = [p for p in root.iterdir() if p.name.casefold() == directory]
            for base in matches:
                _plain(base)
                for current, folders, files in os.walk(base, followlinks=False):
                    for name in folders:
                        _plain(Path(current) / name)
                    for name in sorted(files):
                        path = Path(current) / name
                        if path.suffix.casefold() not in extensions:
                            continue
                        _plain(path)
                        relative = path.relative_to(root).as_posix()
                        key = relative.casefold()
                        if key in seen:
                            raise ValueError(f'Case-colliding asset paths in {mod.name}: {relative}')
                        seen.add(key)
                        stat = path.stat()
                        records.append(dict(mod=mod.name, source=str(path), relative=relative,
                                            key=key, priority=mod.priority, size=stat.st_size,
                                            mtime_ns=stat.st_mtime_ns, sha256=digest(path), metadata=meta))
    return sorted(records, key=lambda r: (r['priority'], r['key'], r['source']))


def _winners(records: list[dict]) -> dict:
    return {r['key']: r for r in sorted(records, key=lambda r: r['priority'])}


def scan(mods: list[Mod], selected: set[str], extensions: set[str], cleanup=True,
         combine=False, output_name='', delete_sources=False) -> Plan:
    extensions = {e.casefold() for e in extensions}
    if not extensions or not extensions <= {'.nif', '.dds'}:
        raise ValueError('Select NIF and/or DDS.')
    if len({m.name for m in mods}) != len(mods) or len({m.priority for m in mods}) != len(mods):
        raise ValueError('Mod names and priorities must be unique.')
    eligible = {m.name for m in mods if m.enabled and not m.separator}
    if not selected or not selected <= eligible:
        raise ValueError('Select at least one enabled regular mod.')
    if delete_sources and not combine:
        raise ValueError('Source removal requires combining.')
    records = inventory(mods, extensions)
    picked = [r for r in records if r['mod'] in selected]
    winners = _winners(picked)
    providers = {}
    for record in picked:
        providers.setdefault(record['key'], []).append(record['mod'])
    effective = _winners(records)
    actions = []
    output = ''
    output_priority = None
    if combine:
        if (not output_name.strip() or output_name != output_name.strip() or
                re.search(r'[<>:"/\\|?*\x00-\x1f]', output_name) or output_name.endswith(('.', ' ')) or
                output_name.startswith(('#', '.')) or output_name.casefold().endswith('_separator') or
                output_name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}):
            raise ValueError('Enter a valid new output mod name.')
        parents = {Path(m.path).absolute().parent for m in mods if not m.separator}
        if len(parents) != 1:
            raise ValueError('Combining requires mods from one mods directory.')
        output_path = next(iter(parents)) / output_name
        if output_path.exists() or any(m.name.casefold() == output_name.casefold() for m in mods):
            raise ValueError('Output mod already exists.')
        output = str(output_path)
        # Find a single insertion slot that preserves all current winning bytes.
        priorities = sorted(m.priority for m in mods)
        remaining = [r for r in records if not (r['mod'] in selected and
                     ((cleanup and r is not winners[r['key']]) or
                      (delete_sources and r is winners[r['key']])))]
        for slot in [*priorities, priorities[-1] + 1]:
            simulated = {}
            for r in remaining:
                simulated.setdefault(r['key'], []).append((r['priority'] * 2, r['sha256']))
            for key, winner in winners.items():
                simulated.setdefault(key, []).append((slot * 2 - 1, winner['sha256']))
            if all(max(simulated[key])[1] == old['sha256'] for key, old in effective.items()):
                output_priority = slot
                break
        if output_priority is None:
            raise ValueError('No safe output placement preserves profile winners.')
    for record in picked:
        winner = winners[record['key']]
        common = dict(record, winner=winner['mod'], winner_source=winner['source'],
                      winner_metadata=winner['metadata'],
                      winner_sha256=winner['sha256'], effective_winner=effective[record['key']]['mod'],
                      providers=providers[record['key']], destination='')
        if record is not winner:
            if cleanup:
                actions.append(dict(common, kind='delete_loser'))
        elif combine:
            destination = str(Path(output) / record['relative'])
            actions.append(dict(common, kind='copy', destination=destination))
            if delete_sources:
                actions.append(dict(common, kind='delete_copied', destination=destination))
    return Plan(mods, set(selected), extensions, actions, records, output, output_priority)


def _inside(path: Path, root: Path):
    _plain(path)
    if not path.absolute().is_relative_to(root.absolute()) or path.absolute() == root.absolute():
        raise ValueError(f'Path escapes testbed: {path}')


def execute(plan: Plan, sandbox_root: Path, logs_root: Path) -> Path:
    """Apply only inside a marked project testbed; live MO2 is preview-only in v0.1."""
    root = Path(sandbox_root).absolute()
    _plain(root)
    marker = root / '.sao-testbed.json'
    if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')).get('format') != 'sao-disposable-v1':
        raise ValueError('Writes require a generated disposable testbed.')
    for mod in plan.mods:
        _inside(Path(mod.path), root / 'mods')
    logs_root = Path(logs_root).absolute()
    _inside(logs_root, root)
    if inventory(plan.mods, plan.extensions) != plan.inventory:
        raise ValueError('Plan is stale: assets or metadata changed. Scan again.')
    for action in plan.actions:
        _inside(Path(action['source']), root / 'mods')
        if action['destination']:
            _inside(Path(action['destination']), root / 'mods')
    if plan.output:
        _inside(Path(plan.output), root / 'mods')
        if Path(plan.output).exists():
            raise ValueError('Output appeared after scanning. Scan again.')
    logs_root.mkdir(parents=True, exist_ok=True)
    log = logs_root / f'{plan.run_id}.jsonl'
    def entry(stream, **data):
        stream.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(), **data), ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    with log.open('x', encoding='utf-8') as stream:
        entry(stream, event='plan', schema=1, run_id=plan.run_id, profile=plan.profile,
              policy='selected-enabled-only; logs-only; shared-folders', selected=sorted(plan.selected),
              mods=[dict(asdict(m), path=str(m.path)) for m in plan.mods], actions=plan.actions)
        report = log.with_suffix('.txt')
        with report.open('x', encoding='utf-8') as summary:
            summary.write(f'Skyrim Asset Organizer - run {plan.run_id}\nProfile: {plan.profile}\n'
                          'Recovery: manual; no removed file backups are retained.\n'
                          'This report lists PLANNED actions; consult JSONL completed/failed events for outcomes.\n'
                          'Recover from a matching download into the original path below. Compare SHA-256 to verify.\n'
                          'Archive paths may differ after FOMOD installation; generated/modified bytes may be unavailable.\n\n')
            for index, action in enumerate(plan.actions):
                summary.write(f"[{index}] {action['kind']}\nOriginal: {action['source']}\n"
                              f"Asset path: {action['relative']}\nSelected winner: {action['winner']}\n"
                              f"Winner path: {action['winner_source']}\nSHA-256: {action['sha256']}\n"
                              f"Output: {action['destination']}\nSource metadata: "
                              + json.dumps(action['metadata'], ensure_ascii=False, indent=2)
                              + '\nSelected winner metadata: '
                              + json.dumps(action['winner_metadata'], ensure_ascii=False, indent=2) + '\n\n')
            summary.flush()
            os.fsync(summary.fileno())
        try:
            # Copies precede any removal, so a failed copy cannot delete sources.
            ordered = sorted(enumerate(plan.actions), key=lambda pair: pair[1]['kind'] != 'copy')
            if plan.output:
                Path(plan.output).mkdir()
                (Path(plan.output) / 'meta.ini').write_text('[General]\nnotes=SAO disposable output\n', encoding='utf-8')
            for index, action in ordered:
                source = Path(action['source'])
                _plain(source)
                if digest(source) != action['sha256']:
                    raise ValueError(f'Source changed: {source}')
                if action['kind'] == 'delete_loser':
                    winner = Path(action['winner_source'])
                    _plain(winner)
                    replacement = Path(plan.output) / action['relative'] if plan.output else winner
                    # Selected winner can already have been relocated to output.
                    if not winner.exists() and plan.output:
                        replacement = next(Path(a['destination']) for a in plan.actions if a['kind']=='copy' and a['key']==action['key'])
                    else:
                        replacement = winner
                    if digest(replacement) != action['winner_sha256']:
                        raise ValueError('Selected winner changed or disappeared.')
                entry(stream, event='intent', index=index, action=action)
                if action['kind'] == 'copy':
                    destination = Path(action['destination'])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with source.open('rb') as src, destination.open('xb') as dst:
                        import shutil
                        shutil.copyfileobj(src, dst)
                        dst.flush()
                        os.fsync(dst.fileno())
                    if digest(destination) != action['sha256']:
                        raise IOError('Output verification failed.')
                else:
                    if action['kind'] == 'delete_copied' and digest(Path(action['destination'])) != action['sha256']:
                        raise IOError('Combined copy is missing or changed.')
                    source.unlink()
                entry(stream, event='completed', index=index)
            if plan.output:
                # Model MO2 activation/placement in the synthetic profile only.
                profile_file = root / 'profile.json'
                _inside(profile_file, root)
                rows = [dict(name=m.name, priority=m.priority + (m.priority >= plan.output_priority),
                             enabled=m.enabled, separator=m.separator) for m in plan.mods]
                rows.append(dict(name=Path(plan.output).name, priority=plan.output_priority, enabled=True, separator=False))
                profile_file.write_text(json.dumps(sorted(rows, key=lambda r:r['priority']), indent=2), encoding='utf-8')
            actual_mods = list(plan.mods)
            if plan.output:
                actual_mods = [Mod(m.name,m.path,m.priority*2,m.enabled,m.separator) for m in plan.mods]
                actual_mods.append(Mod(Path(plan.output).name,Path(plan.output),plan.output_priority*2-1))
            before, after = _winners(plan.inventory), _winners(inventory(actual_mods,plan.extensions))
            if {k:r['sha256'] for k,r in before.items()} != {k:r['sha256'] for k,r in after.items()}:
                raise IOError('Post-operation effective winner verification failed; inspect logs.')
            entry(stream, event='finished')
        except Exception as error:
            entry(stream, event='failed', error=str(error))
            raise
    return log
