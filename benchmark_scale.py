"""Real tiny-file scaling benchmark; never creates or reads 400 GB of assets."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'plugin/SkyrimAssetOrganizer'))
from core import Mod,scan
from journal import asset_log_record
from datetime import datetime,timezone


def peak_memory():
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(n,ctypes.c_size_t) for n in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]
    counters=Counters(); counters.cb=ctypes.sizeof(counters)
    kernel=ctypes.WinDLL('kernel32'); kernel.GetCurrentProcess.restype=ctypes.c_void_p
    psapi=ctypes.WinDLL('psapi'); psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb): raise ctypes.WinError()
    return counters.PeakWorkingSetSize/1024**2


def normalized_log_bytes(path):
    """Measure current encoding from an older generated benchmark plan log."""
    total=0
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            record=json.loads(line)
            record['time']=record.get('time',datetime.now(timezone.utc).isoformat())
            if record['event']=='asset':
                record['sha256']=record['sha256'] or '0'*64
                record=dict(time=record['time'],event='asset',id=record['id'],**asset_log_record(record))
            total+=len((json.dumps(record,separators=(',',':'))+'\n').encode('utf-8'))
    return total


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--files',type=int,default=300000); parser.add_argument('--mods',type=int,default=3000)
    parser.add_argument('--existing',type=Path,help='Reuse a previously generated scale fixture')
    args=parser.parse_args(); root=args.existing or ROOT/'testbeds'/('scale-'+uuid.uuid4().hex[:8])
    if args.existing:
        if not root.resolve().is_relative_to((ROOT/'testbeds').resolve()) or not (root/'.sao-testbed.json').exists(): raise ValueError('Existing fixture must be a marked project testbed')
    else:
        root.mkdir(parents=True); (root/'.sao-testbed.json').write_text('{"format":"sao-disposable-v1"}')
    mods=[]; start=time.perf_counter(); folders=0
    for i in range(args.mods):
        path=root/'mods'/f'Mod {i:04d}'
        if not args.existing:
            path.mkdir(parents=True)
            for group in range(6): (path/'textures/landscape'/f'group{group}').mkdir(parents=True,exist_ok=True)
            for j in range(args.files//args.mods):
                (path/'textures/landscape'/f'group{j%6}'/f'asset{j:04d}.dds').write_bytes(f'asset {i} {j}'.encode())
        mods.append(Mod(path.name,path,i))
        if i%250==0: print(f'Created {i:,} mods',flush=True)
    creation=time.perf_counter()-start; last=[0]
    def progress(message):
        if time.monotonic()-last[0]>10: print(message,flush=True); last[0]=time.monotonic()
    start=time.perf_counter()
    plan=scan(mods,{m.name for m in mods},{'.dds'},combine=True,output_name='Combined',delete_sources=True,progress=progress)
    scan_time=time.perf_counter()-start
    # Measure schema-2 plan section with exactly the records used by execution.
    log=root/'plan-measurement.jsonl'; start=time.perf_counter()
    with plan.connect() as db,log.open('w',encoding='utf-8') as stream:
        def record(**data): stream.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),**data),separators=(',',':'))+'\n')
        for mod in mods: record(event='mod',name=mod.name,path=str(mod.path),metadata=plan.metadata[mod.name])
        for (asset_id,) in db.execute('select source_id from actions union select winner_id from actions'):
            data=json.loads(db.execute('select data from assets where id=?',(asset_id,)).fetchone()[0])
            # Size model only: preview deliberately has no content hashes.
            data['sha256']=data['sha256'] or '0'*64
            record(event='asset',id=asset_id,**asset_log_record(data))
        for index,source,winner,kind,data in db.execute('select * from actions'):
            action=json.loads(data); record(event='planned',index=index,kind=kind,source_id=source,winner_id=winner,destination=action['destination'])
        stream.flush(); os.fsync(stream.fileno())
    results=dict(files=plan.stats['files'],mods=len(mods),creation_seconds=creation,scan_seconds=scan_time,peak_working_set_MiB=peak_memory(),index_MiB=plan.database.stat().st_size/1024**2,actions=len(plan.actions),hashed_bytes=plan.stats['hashed_bytes'],plan_log_MiB=log.stat().st_size/1024**2,plan_log_seconds=time.perf_counter()-start,scope='real tiny files; no mutation; plan-log sizing uses placeholder hashes; no 400GB throughput claim')
    (root/'results.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2),flush=True); print(root,flush=True)
    plan.close()


if __name__=='__main__': main()
