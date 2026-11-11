"""Normalized streaming journal with durable batch intent before mutations."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
try:
    from .core import Plan, _index, _record, _hash, _inside, _plain, digest
except ImportError:
    from core import Plan, _index, _record, _hash, _inside, _plain, digest


def asset_log_record(record):
    # Full original paths reconstruct from the one mod-root record plus relative.
    return {key:record[key] for key in ('mod','relative','size','mtime_ns','sha256')}


def execute_plan(plan,sandbox_root,logs_root):
    root=Path(sandbox_root).absolute(); _plain(root)
    marker=root/'.sao-testbed.json'
    if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')).get('format')!='sao-disposable-v1': raise ValueError('Writes require a generated disposable testbed.')
    def check_profile():
        actual=digest(plan.profile_path) if plan.profile_path and plan.profile_path.exists() else None
        if actual!=plan.profile_digest: raise ValueError('Profile is stale: reload and scan again.')
    check_profile()
    for mod in plan.mods: _inside(mod.path,root/'mods')
    logs_root=Path(logs_root).absolute(); _inside(logs_root,root)
    if plan.output:
        _inside(plan.output,root/'mods')
        if Path(plan.output).exists(): raise ValueError('Output appeared after scanning. Scan again.')
    fresh=Plan(plan.mods,plan.selected,plan.extensions)
    try:
        with fresh.connect() as check: _index(fresh,check,lambda text:None,None)
        with plan.connect() as db,fresh.connect() as check:
            import itertools
            query='select mod,key,size,mtime from assets order by mod,key'
            if plan.metadata!=fresh.metadata or any(a!=b for a,b in itertools.zip_longest(db.execute(query),check.execute(query))): raise ValueError('Plan is stale: assets or metadata changed. Scan again.')
    finally: fresh.close()
    check_profile()
    for action in plan.actions:
        _inside(action['source'],root/'mods')
        if action['destination']: _inside(action['destination'],root/'mods')
    # Build the complete hash/provenance manifest before any asset mutation.
    # Nothing is deleted if this phase fails; preview itself reads no content.
    with plan.connect() as db:
        for index,source_id,winner_id,data in db.execute('select id,source_id,winner_id,data from actions order by id'):
            source=_hash(db,plan,source_id,None); winner=_hash(db,plan,winner_id,None)
            action=json.loads(data); action['sha256']=source['sha256']; action['winner_sha256']=winner['sha256']
            db.execute('update actions set data=? where id=?',(json.dumps(action,separators=(',',':')),index))
    logs_root.mkdir(parents=True,exist_ok=True); log=logs_root/f'{plan.run_id}.jsonl'
    def entry(stream,sync=False,**data):
        stream.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),**data),ensure_ascii=False,separators=(',',':'))+'\n')
        if sync: stream.flush(); os.fsync(stream.fileno())
    with plan.connect() as db, log.open('x',encoding='utf-8') as stream:
        entry(stream,event='plan',schema=2,run_id=plan.run_id,profile=plan.profile,output=plan.output,output_priority=plan.output_priority,extensions=sorted(plan.extensions),policy='selected-enabled-only; logs-only; shared-folders')
        for mod in plan.mods: entry(stream,event='mod',name=mod.name,path=str(mod.path),priority=mod.priority,enabled=mod.enabled,separator=mod.separator,selected=mod.name in plan.selected,metadata=plan.metadata.get(mod.name,{}))
        for (asset_id,) in db.execute('select source_id from actions union select winner_id from actions'): entry(stream,event='asset',id=asset_id,**asset_log_record(_record(db,asset_id)))
        for index,source_id,winner_id,kind,data in db.execute('select * from actions order by id'):
            entry(stream,event='planned',index=index,kind=kind,source_id=source_id,winner_id=winner_id,destination=json.loads(data)['destination'])
        entry(stream,sync=True,event='plan_saved',actions=len(plan.actions))
        with log.with_suffix('.txt').open('x',encoding='utf-8') as summary:
            summary.write(f'SAO run {plan.run_id}\nProfile: {plan.profile}\nActions: {len(plan.actions):,}\nRecovery: logs only; no asset backups.\nUse log_report.py to browse/search/export the accompanying schema-2 JSONL.\nCompleted/failed events determine outcomes. Interrupted batches can have uncertain actions.\n')
            summary.flush(); os.fsync(summary.fileno())
        # Disk-backed verified fingerprints avoid another large Python map.
        db.execute('create table if not exists verified(path text primary key,size int,mtime int,ctime int)')
        def verify(path,expected):
            path=Path(path); _plain(path); stat=path.stat(); token=(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
            previous=db.execute('select size,mtime,ctime from verified where path=?',(str(path),)).fetchone()
            if previous!=token:
                if digest(path)!=expected: raise ValueError(f'Source or winner changed: {path}')
                db.execute('insert or replace into verified values(?,?,?,?)',(str(path),*token))
        try:
            if plan.output:
                Path(plan.output).mkdir(); (Path(plan.output)/'meta.ini').write_text('[General]\nnotes=SAO disposable output\n',encoding='utf-8')
            for copying in (True,False):
                cursor=db.execute('select id,data,winner_id from actions where '+("kind='copy'" if copying else "kind!='copy'")+' order by id')
                while batch:=cursor.fetchmany(128):
                    entry(stream,sync=True,event='batch_intent',indices=[r[0] for r in batch])
                    for index,data,winner_id in batch:
                        action=json.loads(data); source=Path(action['source']); verify(source,action['sha256'])
                        if copying:
                            import shutil
                            dst=Path(action['destination']); _inside(dst,root/'mods'); dst.parent.mkdir(parents=True,exist_ok=True)
                            with source.open('rb') as src,dst.open('xb') as target:
                                shutil.copyfileobj(src,target,1024*1024); target.flush(); os.fsync(target.fileno())
                            verify(dst,action['sha256'])
                        else:
                            if action['kind']=='delete_copied': verify(action['destination'],action['sha256'])
                            else:
                                winner=Path(action['winner_source'])
                                if not winner.exists() and plan.output:
                                    row=db.execute("select data from actions where winner_id=? and kind='copy'",(winner_id,)).fetchone()
                                    if row is None: raise ValueError('Selected winner disappeared')
                                    winner=Path(json.loads(row[0])['destination'])
                                verify(winner,action['winner_sha256'])
                            source.unlink()
                        entry(stream,event='completed',index=index)
                    entry(stream,sync=True,event='batch_finished'); db.commit()
                if copying and plan.output:
                    # Publish verified output activation before removing sources.
                    check_profile()
                    profile_file=root/'profile.json'; _inside(profile_file,root)
                    temporary=root/f'.profile-{plan.run_id}.tmp'; _inside(temporary,root)
                    rows=[dict(name=m.name,priority=m.priority+(m.priority>=plan.output_priority),enabled=m.enabled,separator=m.separator) for m in plan.mods]
                    rows.append(dict(name=Path(plan.output).name,priority=plan.output_priority,enabled=True,separator=False))
                    entry(stream,sync=True,event='profile_publish_intent')
                    with temporary.open('x',encoding='utf-8') as target:
                        json.dump(sorted(rows,key=lambda r:r['priority']),target,indent=2)
                        target.flush(); os.fsync(target.fileno())
                    os.replace(temporary,profile_file)
                    entry(stream,sync=True,event='profile_published')
            for effective_id,chosen_id in db.execute('select e.id,c.id from effective e join chosen c on e.key=c.key'):
                record=_record(db,effective_id)
                if record['sha256']:
                    target=Path(record['source'])
                    if plan.output and chosen_id==effective_id and not target.exists(): target=Path(plan.output)/record['relative']
                    verify(target,record['sha256'])
            entry(stream,sync=True,event='finished')
        except Exception as error:
            entry(stream,sync=True,event='failed',error=str(error)); raise
    return log
