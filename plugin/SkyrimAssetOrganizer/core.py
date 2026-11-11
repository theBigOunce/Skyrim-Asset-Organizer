"""Disk-backed asset planning; mutations remain restricted to disposable fixtures."""
import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
import weakref
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
try:
    from .common import Mod, metadata, _plain
except ImportError:
    from common import Mod, metadata, _plain


class ScanCancelled(Exception): pass


def digest(path,cancel=None):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(1024*1024):
            if cancel and cancel(): raise ScanCancelled('Scan cancelled')
            value.update(chunk)
    return value.hexdigest()


class DiskRows(Sequence):
    def __init__(self,plan,table): self.plan=weakref.proxy(plan); self.table=table
    def __len__(self):
        return self.plan.action_count if self.table=='actions' else self.plan.stats['files']
    def expand(self,row):
        value=json.loads(row[0]); value['metadata']=self.plan.metadata[value['mod']]
        if 'winner' in value: value['winner_metadata']=self.plan.metadata[value['winner']]
        return value
    def __getitem__(self,index):
        if isinstance(index,slice): return [self[i] for i in range(*index.indices(len(self)))]
        if index<0: index+=len(self)
        with self.plan.connect() as db:
            row=db.execute(f'select data from {self.table} where id=?',(index,)).fetchone()
            if row is None: raise IndexError(index)
            return self.expand(row)
    def __iter__(self):
        with self.plan.connect() as db:
            for row in db.execute(f'select data from {self.table} order by id'): yield self.expand(row)


class Plan:
    def __init__(self,mods,selected,extensions):
        cache=Path(__file__).resolve().parents[2]/'.sao-cache'; cache.mkdir(exist_ok=True)
        self._temp=tempfile.TemporaryDirectory(dir=cache)
        self.database=Path(self._temp.name)/'plan.sqlite'
        self.mods=mods; self.selected=selected; self.extensions=extensions; self.metadata={}
        self.actions=DiskRows(self,'actions'); self.inventory=DiskRows(self,'assets')
        self.output=''; self.output_priority=None; self.run_id=uuid.uuid4().hex; self.profile='Selected profile'
        self.stats={'files':0,'hashed_files':0,'hashed_bytes':0}
        self.action_count=0
        parents={Path(m.path).absolute().parent for m in mods if not m.separator}
        self.profile_path=next(iter(parents)).parent/'profile.json' if len(parents)==1 else None
        self.profile_digest=digest(self.profile_path) if self.profile_path and self.profile_path.exists() else None
        if self.profile_digest:
            expected=[dict(name=m.name,priority=m.priority,enabled=m.enabled,separator=m.separator) for m in mods]
            actual=json.loads(self.profile_path.read_text(encoding='utf-8'))
            if sorted(expected,key=lambda r:r['priority'])!=sorted(actual,key=lambda r:r['priority']):
                self.close(); raise ValueError('Profile changed: reload the modlist before scanning.')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.database)
        # This database is disposable scan state, never the recovery journal.
        # Avoid rollback-journal fsyncs when its small page cache spills.
        db.execute('pragma journal_mode=OFF')
        db.execute('pragma synchronous=OFF')
        db.execute('pragma cache_size=-4096')
        db.execute('pragma temp_store=FILE')
        try:
            with db: yield db
        finally: db.close()
    def close(self): self._temp.cleanup()
    def __del__(self):
        try: self.close()
        except (AttributeError,OSError): pass


def _cancel(cancel):
    if cancel and cancel(): raise ScanCancelled('Scan cancelled')


def _index(plan,db,progress,cancel):
    db.execute('create table assets(id integer primary key,mod text,key text,priority int,size int,mtime int,data text,unique(mod,key))')
    db.execute('create table actions(id integer primary key,source_id int,winner_id int,kind text,data text)')
    for mod in sorted(plan.mods,key=lambda m:m.priority):
        _cancel(cancel)
        if not mod.enabled or mod.separator: continue
        root=Path(mod.path).absolute(); _plain(root)
        if not root.is_dir(): raise ValueError(f'Mod directory missing: {root}')
        plan.metadata[mod.name]=metadata(root)
        progress(f'Indexing {mod.name}: {plan.stats["files"]:,} files')
        for base in [p for p in root.iterdir() if p.name.casefold() in ('meshes','textures')]:
            _entry(base)
            def traversal_error(error): raise error
            for current,folders,files in os.walk(base,followlinks=False,onerror=traversal_error):
                _cancel(cancel)
                for folder in folders: _entry(Path(current)/folder)
                for name in files:
                    path=Path(current)/name
                    if path.suffix.casefold() not in plan.extensions: continue
                    _entry(path); stat=path.stat(); relative=path.relative_to(root).as_posix()
                    row=dict(mod=mod.name,source=str(path),relative=relative,key=relative.casefold(),priority=mod.priority,size=stat.st_size,mtime_ns=stat.st_mtime_ns,sha256=None)
                    try: db.execute('insert into assets values(?,?,?,?,?,?,?)',(plan.stats['files'],mod.name,row['key'],mod.priority,stat.st_size,stat.st_mtime_ns,json.dumps(row,separators=(',',':'))))
                    except sqlite3.IntegrityError: raise ValueError(f'Case-colliding asset paths in {mod.name}: {relative}')
                    plan.stats['files']+=1
        db.commit()
    db.execute('create index asset_path on assets(key,priority)')
    db.execute('create table selection(name text primary key)')
    db.executemany('insert into selection values(?)',[(name,) for name in plan.selected])
    db.execute('create table chosen as select a.* from assets a join (select key,max(priority) p from assets join selection on mod=name group by key) w on a.key=w.key and a.priority=w.p')
    db.execute('create unique index chosen_key on chosen(key)')
    db.execute('create table effective as select a.* from assets a join (select key,max(priority) p from assets group by key) w on a.key=w.key and a.priority=w.p')
    db.execute('create unique index effective_key on effective(key)')


def _entry(path):
    stat=path.lstat()
    if path.is_symlink() or getattr(stat,'st_file_attributes',0)&0x400: raise ValueError(f'Reparse point is not supported: {path}')


def _record(db,asset_id): return json.loads(db.execute('select data from assets where id=?',(asset_id,)).fetchone()[0])


def _hash(db,plan,asset_id,cancel):
    record=_record(db,asset_id)
    if not record['sha256']:
        path=Path(record['source']); before=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(record['size'],record['mtime_ns']): raise ValueError(f'Asset changed during scan: {path}')
        record['sha256']=digest(path,cancel)
        if path.stat().st_mtime_ns!=before.st_mtime_ns: raise ValueError(f'Asset changed during scan: {path}')
        plan.stats['hashed_files']+=1; plan.stats['hashed_bytes']+=record['size']
        db.execute('update assets set data=? where id=?',(json.dumps(record,separators=(',',':')),asset_id))
    return record


def scan(mods,selected,extensions,cleanup=True,combine=False,output_name='',delete_sources=False,progress=None,cancel=None):
    extensions={e.casefold() for e in extensions}; progress=progress or (lambda text:None)
    if not extensions or not extensions<={'.nif','.dds'}: raise ValueError('Select NIF and/or DDS.')
    if len({m.name for m in mods})!=len(mods) or len({m.priority for m in mods})!=len(mods): raise ValueError('Mod names and priorities must be unique.')
    if not selected or not selected<={m.name for m in mods if m.enabled and not m.separator}: raise ValueError('Select at least one enabled regular mod.')
    if delete_sources and not combine: raise ValueError('Source removal requires combining.')
    plan=Plan(mods,set(selected),extensions)
    try:
        with plan.connect() as db:
            _index(plan,db,progress,cancel)
            if combine:
                import re
                if (not output_name.strip() or output_name!=output_name.strip() or re.search(r'[<>:"/\\|?*\x00-\x1f]',output_name) or output_name.endswith(('.', ' ')) or output_name.startswith(('#','.')) or output_name.casefold().endswith('_separator') or output_name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}): raise ValueError('Enter a valid new output mod name.')
                parents={Path(m.path).absolute().parent for m in mods if not m.separator}
                if len(parents)!=1: raise ValueError('Combining requires mods from one mods directory.')
                output=next(iter(parents))/output_name
                if output.exists() or any(m.name.casefold()==output_name.casefold() for m in mods): raise ValueError('Output mod already exists.')
                plan.output=str(output)
                lower=min(m.priority for m in mods); upper=max(m.priority for m in mods)+1
                for chosen_id,effective_id,priority in db.execute('select c.id,e.id,e.priority from chosen c join effective e on c.key=e.key'):
                    _cancel(cancel)
                    if chosen_id!=effective_id: upper=min(upper,priority)
                    elif delete_sources:
                        below=db.execute('select max(priority) from assets where key=(select key from assets where id=?) and id!=? and (?=0 or mod not in(select name from selection))',(chosen_id,chosen_id,int(cleanup))).fetchone()[0]
                        if below is not None: lower=max(lower,below+1)
                slots=[p for p in sorted({m.priority for m in mods}|{max(m.priority for m in mods)+1}) if lower<=p<=upper]
                if not slots: raise ValueError('No safe output placement preserves profile winners.')
                plan.output_priority=slots[0]
            count=0
            for source_id,winner_id,effective_mod in db.execute('select a.id,c.id,e.mod from assets a join selection on a.mod=name join chosen c on a.key=c.key join effective e on a.key=e.key order by a.priority,a.key'):
                _cancel(cancel)
                kinds=['delete_loser'] if source_id!=winner_id and cleanup else (['copy']+(['delete_copied'] if delete_sources else []) if source_id==winner_id and combine else [])
                if not kinds: continue
                # Path conflicts and conservative placement do not require
                # reading content. Capture hashes only at verified execution.
                source=_record(db,source_id); winner=_record(db,winner_id)
                common=dict(source,winner=winner['mod'],winner_source=winner['source'],winner_sha256=winner['sha256'],effective_winner=effective_mod,destination=str(Path(plan.output)/source['relative']) if combine and source_id==winner_id else '')
                for kind in kinds:
                    db.execute('insert into actions values(?,?,?,?,?)',(count,source_id,winner_id,kind,json.dumps(dict(common,kind=kind),separators=(',',':')))); count+=1
                if count%1000==0: progress(f'Planning {count:,} actions; hashed {plan.stats["hashed_bytes"]:,} bytes')
            plan.action_count=count
            db.execute('create index actions_winner on actions(winner_id,kind)')
            db.commit()
        progress(f'Ready: {plan.stats["files"]:,} indexed; {len(plan.actions):,} actions')
        return plan
    except BaseException: plan.close(); raise


def _inside(path,root):
    path=Path(path); root=Path(root); _plain(path)
    if not path.resolve().is_relative_to(root.resolve()) or path.resolve()==root.resolve(): raise ValueError(f'Path escapes testbed: {path}')


def execute(plan,sandbox_root,logs_root):
    try:
        from .journal import execute_plan
    except ImportError:
        from journal import execute_plan
    return execute_plan(plan,sandbox_root,logs_root)
