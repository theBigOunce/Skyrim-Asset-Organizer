"""Search schema-2 logs without loading the whole log into RAM.

Example: python log_report.py run.jsonl --mod "Landscape Base" --contains rock --limit 100
"""
import argparse
import json
import sqlite3
import tempfile
from contextlib import closing


def report(path,mod='',contains='',limit=100):
    # A temporary disk index resolves source/winner IDs and outcome events.
    import pathlib
    cache=pathlib.Path(__file__).resolve().parent/'.sao-cache'; cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as temporary:
        with closing(sqlite3.connect(str(pathlib.Path(temporary)/'log.sqlite'))) as db, open(path,encoding='utf-8') as logfile:
            # Disposable search index; durable recovery data stays in JSONL.
            db.execute('pragma journal_mode=OFF')
            db.execute('pragma synchronous=OFF')
            db.execute('pragma cache_size=-4096')
            db.execute('pragma temp_store=FILE')
            db.execute('create table mods(name text primary key,data text)')
            db.execute('create table assets(id integer primary key,mod text,path text,data text)')
            db.execute('create table actions(id integer primary key,source int,winner int,kind text,destination text,status text)')
            for line in logfile:
                try: r=json.loads(line)
                except json.JSONDecodeError:
                    if not line.endswith('\n'): break  # interrupted final record
                    raise
                event=r['event']
                if event=='plan' and r.get('schema')!=2: raise ValueError('This viewer supports schema-2 logs; original demo logs use schema 1.')
                if event=='mod': db.execute('insert into mods values(?,?)',(r['name'],json.dumps(r)))
                elif event=='asset': db.execute('insert into assets values(?,?,?,?)',(r['id'],r['mod'],r['relative'],json.dumps(r)))
                elif event=='planned': db.execute('insert into actions values(?,?,?,?,?,?)',(r['index'],r['source_id'],r['winner_id'],r['kind'],r['destination'],'planned'))
                elif event=='batch_intent': db.executemany("update actions set status='intent; outcome uncertain' where id=?",[(i,) for i in r['indices']])
                elif event=='completed': db.execute("update actions set status='completed' where id=?",(r['index'],))
            query='select a.id,a.kind,a.status,s.data,w.data,m.data,a.destination from actions a join assets s on a.source=s.id join assets w on a.winner=w.id join mods m on s.mod=m.name where (?=\'\' or s.mod=?) and instr(lower(s.path),lower(?))>0 order by a.id limit ?'
            for index,kind,status,source,winner,meta,destination in db.execute(query,(mod,mod,contains,limit)):
                source=json.loads(source); source_mod=json.loads(meta); winner=json.loads(winner)
                winner_mod=json.loads(db.execute('select data from mods where name=?',(winner['mod'],)).fetchone()[0])
                source['source']=str(pathlib.Path(source_mod['path'])/source['relative'])
                winner['source']=str(pathlib.Path(winner_mod['path'])/winner['relative'])
                yield dict(index=index,kind=kind,status=status,source=source,winner=winner,source_mod=source_mod,winner_mod=winner_mod,destination=destination)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('log'); parser.add_argument('--mod',default=''); parser.add_argument('--contains',default=''); parser.add_argument('--limit',type=int,default=100)
    args=parser.parse_args()
    for row in report(args.log,args.mod,args.contains,args.limit): print(json.dumps(row,ensure_ascii=False,indent=2))
