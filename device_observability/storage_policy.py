"""Bounded local storage. Never deletes keys, budgets, reports or backups."""
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import time
from contextlib import closing

MIB = 1024**2


def storage_status(directory, maximum, minimum_free=0):
    physical = logical = 0
    for path in Path(directory).iterdir():
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode):
            continue
        physical += info.st_size
        used=info.st_size
        if path.suffix=='.sqlite3' and info.st_size:
            try:
                with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as con:
                    pages=con.execute('PRAGMA page_count').fetchone()[0]
                    free=con.execute('PRAGMA freelist_count').fetchone()[0]
                    size=con.execute('PRAGMA page_size').fetchone()[0]
                    used=(pages-free)*size
            except sqlite3.Error:
                pass
        logical += used
    free=shutil.disk_usage(directory).free
    return {'physical_bytes':physical,'active_bytes':logical,'limit_bytes':maximum,
            'free_bytes':free,'minimum_free_bytes':minimum_free,
            'ratio':logical/maximum,'blocked':logical>=maximum or free<minimum_free,
            'warning':logical>=maximum*.8 or free<max(minimum_free*2,512*MIB),
            'scope':'Managed local state; external backups and system logs are not included.'}


def ensure_capacity(directory, maximum, minimum_free=0, additional_bytes=0):
    current=storage_status(directory,maximum,minimum_free)
    if current['free_bytes'] < minimum_free + additional_bytes:
        raise OSError('Pouco espaço livre no disco. Libere espaço ou revise Armazenamento em Configurações; o histórico confirmado foi preservado.')
    if current['active_bytes'] + additional_bytes > maximum:
        raise OSError('A cota de armazenamento foi atingida. Revise a retenção ou a cota em Configurações; novas gravações estão limitadas.')
    return current


def maintain(con, config):
    if not config.retention_days:
        return {'deleted':0}
    usage=storage_status(config.data_dir,config.max_storage_bytes,config.minimum_free_bytes)
    pressure=usage['active_bytes'] >= config.max_storage_bytes*.85
    cutoff=time.time_ns()-config.retention_days*86400*1_000_000_000
    rows=con.execute('''SELECT id,utc_ns FROM samples WHERE id<(SELECT COALESCE(MAX(id),0)-1 FROM samples)
                        AND (? OR utc_ns<?) ORDER BY id LIMIT 1000''',(pressure,cutoff)).fetchall()
    if not rows:return {'deleted':0}
    con.execute('BEGIN IMMEDIATE')
    try:
        con.executemany('DELETE FROM samples WHERE id=?',[(r[0],) for r in rows])
        prior=con.execute("SELECT value FROM metadata WHERE key='raw_pruned_max_utc_ns'").fetchone()
        maximum=max([r[1] for r in rows]+[int(prior[0]) if prior else 0])
        con.execute("INSERT OR REPLACE INTO metadata VALUES ('raw_pruned_max_utc_ns',?)",(str(maximum),))
        con.execute('DELETE FROM events WHERE id IN (SELECT id FROM events WHERE utc_ns<? ORDER BY id LIMIT 1000)',(cutoff,))
        con.commit()
    except BaseException:
        con.rollback();raise
    return {'deleted':len(rows),'cutoff_utc_ns':maximum,'pressure':pressure}
