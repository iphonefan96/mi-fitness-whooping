#!/usr/bin/env python3
"""Read-only metadata profiling of the production Mi Fitness SQLite database.

No health samples are exported. Output contains counts, ranges, coverage, and
source-key names only. Run against a quiescent database or verify the before/after
file signature; immutable SQLite mode prevents creation of SHM/WAL files.
"""

import argparse
import collections
import datetime as dt
import json
import math
import os
import re
import sqlite3
import statistics
from pathlib import Path


KEY_PATTERN = re.compile(
    r"hrv|rmssd|sdnn|pnn|(?:^|[^a-z])rr(?:[^a-z]|$)|rr_?interval|rri|ibi|"
    r"interbeat|beat_?interval|heart_?variability|respir|breath|temperat|"
    r"skin_?temp|wrist_?temp|recovery|readiness|vitality|training_?load|"
    r"sleep_?score|sleep_?quality|stress|weight|height|gender|sex|birth|age",
    re.I,
)
TIME_COLUMNS = (
    "timestamp_utc", "source_timestamp", "sleep_start_utc", "start_timestamp_utc",
    "window_start_utc", "started_at", "last_seen_at",
)
DAY_COLUMNS = ("local_date",)
SOURCE_COLUMNS = ("kind", "origin", "source_table", "event_type", "stage", "workout_type", "sport_type", "warning_type", "status")
EXCLUDE_NUMERIC = {"source_db_id", "sample_index", "stage_index", "source_deleted", "has_stages", "has_rem", "is_nap_inferred", "raw_state", "utc_offset_seconds", "warning_id"}


def query(con, sql, args=()):
    return [dict(row) for row in con.execute(sql, args)]


def one(con, sql, args=()):
    return dict(con.execute(sql, args).fetchone())


def ident(s):
    return '"' + s.replace('"', '""') + '"'


def rounded(value, digits=3):
    return round(value, digits) if value is not None else None


def quantiles(values):
    if not values:
        return {}
    values = sorted(values)
    return {str(p): rounded(values[round((len(values)-1)*p/100)]) for p in (10, 25, 50, 75, 90, 95, 99)}


def walk_keys(obj, prefix=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, value
            if isinstance(value, (dict, list, str)):
                yield from walk_keys(value, path)
    elif isinstance(obj, list):
        for value in obj:
            if isinstance(value, (dict, list, str)):
                yield from walk_keys(value, prefix + "[]")
    elif isinstance(obj, str) and obj[:1] in ("{", "["):
        try:
            yield from walk_keys(json.loads(obj), prefix + "{json}")
        except (ValueError, TypeError):
            pass


def file_signature(path):
    st = path.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "inode": st.st_ino}


def profile(con, db_path):
    result = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "db_path": str(db_path), "file_before": file_signature(db_path)}
    names = [r["name"] for r in query(con, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    tables = {}
    for name in names:
        qn = ident(name)
        columns = query(con, f"PRAGMA table_info({qn})")
        colnames = [c["name"] for c in columns]
        entry = {"columns": columns, "indexes": query(con, f"PRAGMA index_list({qn})"), "rows": one(con, f"SELECT count(*) n FROM {qn}")["n"]}
        if entry["rows"]:
            entry["nulls"] = one(con, "SELECT " + ",".join(f"sum({ident(c)} IS NULL) AS {ident(c)}" for c in colnames) + f" FROM {qn}")
            for col in TIME_COLUMNS:
                if col in colnames:
                    entry["time"] = one(con, f"SELECT min({ident(col)}) min, max({ident(col)}) max FROM {qn}")
                    break
            for col in DAY_COLUMNS:
                if col in colnames:
                    entry["days"] = one(con, f"SELECT count(distinct {ident(col)}) distinct_days,min({ident(col)}) min,max({ident(col)}) max FROM {qn}")
                    break
            numerical = [c["name"] for c in columns if c["type"].upper() in ("INTEGER", "REAL", "NUMERIC") and c["name"] not in EXCLUDE_NUMERIC and "timestamp" not in c["name"] and not c["name"].endswith("_utc")]
            entry["numeric"] = {}
            for col in numerical:
                entry["numeric"][col] = one(con, f"SELECT min({ident(col)}) min,max({ident(col)}) max,avg({ident(col)}) mean,sum({ident(col)} IS NOT NULL) n FROM {qn}")
            entry["distributions"] = {}
            for col in SOURCE_COLUMNS:
                if col in colnames:
                    entry["distributions"][col] = query(con, f"SELECT {ident(col)} value,count(*) n FROM {qn} GROUP BY {ident(col)} ORDER BY n DESC LIMIT 40")
        tables[name] = entry
    result["tables"] = tables

    source_dbs = query(con, "SELECT source_db_id,relative_path,max_source_timestamp,is_health_database FROM source_databases ORDER BY source_db_id")
    result["source_databases"] = [{"source_db_id":r["source_db_id"],"region":next((part for part in Path(r["relative_path"]).parts if part in ("cn","ru")),"other"),"max_source_timestamp":r["max_source_timestamp"],"is_health_database":r["is_health_database"]} for r in source_dbs]
    result["source_catalog"] = query(con, "SELECT source_db_id,table_name,columns_json,primary_key_json FROM source_table_catalog ORDER BY source_db_id,table_name")
    result["derived_metrics"] = query(con, "SELECT source_table,field_path,metric_name,origin,count(*) n,count(numeric_value) numeric_n,min(numeric_value) min,max(numeric_value) max,min(local_date) first_day,max(local_date) last_day,count(distinct local_date) days FROM derived_metrics GROUP BY source_table,field_path,metric_name,origin ORDER BY n DESC")
    result["raw_blobs"] = query(con, "SELECT column_name,count(*) n,min(length(data)) min_bytes,max(length(data)) max_bytes,sum(length(data)) total_bytes,hex(substr(data,1,4)) magic FROM raw_blobs GROUP BY column_name ORDER BY n DESC")
    result["schema_info"] = query(con, "SELECT key,value FROM schema_info")

    result["hr"] = {}
    hr = result["hr"]
    hr["by_kind"] = query(con, "SELECT kind,count(*) n,count(distinct local_date) days,min(bpm) min,max(bpm) max FROM heart_rate GROUP BY kind ORDER BY n DESC")
    hr["duplicates"] = one(con, "SELECT count(*) duplicate_time_groups,sum(n-1) excess_rows FROM (SELECT timestamp_utc,count(*) n FROM heart_rate GROUP BY timestamp_utc HAVING n>1)")
    hr["ranges"] = one(con, "SELECT sum(bpm<25) below25,sum(bpm>240) above240,min(bpm) min,max(bpm) max,count(distinct local_date) observed_days FROM heart_rate")
    hr["quality_keys"] = query(con, "SELECT table_name,columns_json FROM source_table_catalog WHERE table_name LIKE '%heart%' LIMIT 20")
    # Whole-series delta statistics; duplicate timestamps kept visible as zero intervals.
    deltas = [r[0] for r in con.execute("SELECT timestamp_utc-lag(timestamp_utc) OVER (ORDER BY timestamp_utc) FROM heart_rate") if r[0] is not None]
    hr["intervals_all_seconds"] = {"n": len(deltas), "quantiles": quantiles(deltas), "mean": rounded(statistics.fmean(deltas))}
    bounds = [("<=2", lambda x:x<=2), ("3-5", lambda x:2<x<=5), ("6-15",lambda x:5<x<=15), ("16-30",lambda x:15<x<=30), ("31-60",lambda x:30<x<=60), ("61-300",lambda x:60<x<=300), (">300",lambda x:x>300)]
    hr["interval_buckets_all"] = {k:sum(test(x) for x in deltas) for k,test in bounds}
    # Gaps >6 h are not treated as physiological intervals when comparing sampling modes.
    day_intervals, night_intervals = [], []
    for row in con.execute("SELECT timestamp_utc,local_timestamp,timestamp_utc-lag(timestamp_utc) OVER (ORDER BY timestamp_utc) gap FROM heart_rate"):
        if row["gap"] is None or row["gap"] > 21600:
            continue
        # Clock in existing local_timestamp; do not infer timezone from machine locale.
        clock = row["local_timestamp"]
        hour = (clock // 3600) % 24 if clock is not None else (row["timestamp_utc"] // 3600) % 24
        (night_intervals if hour < 9 or hour >= 22 else day_intervals).append(row["gap"])
    hr["intervals_clock_night"] = {"n":len(night_intervals), "quantiles":quantiles(night_intervals)}
    hr["intervals_clock_day"] = {"n":len(day_intervals), "quantiles":quantiles(day_intervals)}
    sleep_windows=[(r[0],r[1]) for r in con.execute("SELECT sleep_start_utc,sleep_end_utc FROM sleep_sessions WHERE is_nap_inferred=0 ORDER BY sleep_start_utc")]
    sleep_gap,outside_gap=[],[]
    window_index=0
    previous_time=previous_sleep=None
    for (stamp,) in con.execute("SELECT timestamp_utc FROM heart_rate ORDER BY timestamp_utc"):
        while window_index<len(sleep_windows) and sleep_windows[window_index][1]<=stamp:
            window_index+=1
        in_sleep=window_index<len(sleep_windows) and sleep_windows[window_index][0]<=stamp<sleep_windows[window_index][1]
        if previous_time is not None and in_sleep==previous_sleep:
            gap=stamp-previous_time
            if 0<=gap<=21600:
                (sleep_gap if in_sleep else outside_gap).append(gap)
        previous_time,previous_sleep=stamp,in_sleep
    hr["intervals_within_sleep"]={"n":len(sleep_gap),"quantiles":quantiles(sleep_gap),"buckets":{k:sum(test(x) for x in sleep_gap) for k,test in bounds}}
    hr["intervals_outside_sleep"]={"n":len(outside_gap),"quantiles":quantiles(outside_gap),"buckets":{k:sum(test(x) for x in outside_gap) for k,test in bounds}}
    hr["dense_runs"] = one(con, "WITH d AS (SELECT timestamp_utc, timestamp_utc-lag(timestamp_utc) OVER (ORDER BY timestamp_utc) gap FROM heart_rate), g AS (SELECT *,sum(CASE WHEN gap BETWEEN 1 AND 2 THEN 0 ELSE 1 END) OVER (ORDER BY timestamp_utc) grp FROM d), runs AS (SELECT grp,count(*) n,min(timestamp_utc) start,max(timestamp_utc) finish FROM g GROUP BY grp) SELECT max(n) longest_samples,max(finish-start) longest_seconds,sum(n>=30) runs_at_least_30_samples FROM runs")
    hr["daily_counts"] = query(con, "SELECT local_date,count(*) n,min(bpm) min_bpm,max(bpm) max_bpm FROM heart_rate GROUP BY local_date ORDER BY local_date")
    hr["night_counts"] = query(con, "SELECT s.local_date,count(h.source_record_id) n,count(distinct h.timestamp_utc/300) bins5 FROM sleep_sessions s LEFT JOIN heart_rate h ON h.timestamp_utc>=s.sleep_start_utc AND h.timestamp_utc<s.sleep_end_utc WHERE s.sleep_start_utc IS NOT NULL AND s.sleep_end_utc IS NOT NULL GROUP BY s.source_record_id ORDER BY s.local_date")

    result["sleep"] = {}
    sleep = result["sleep"]
    sessions = query(con, "SELECT local_date,source_record_id,sleep_start_utc,sleep_end_utc,duration_minutes,deep_minutes,light_minutes,rem_minutes,awake_minutes,sleep_score,sleep_efficiency,avg_hr,min_hr,max_hr,avg_spo2,min_spo2,max_spo2,avg_respiratory_rate,breathing_quality,awake_count,has_stages,has_rem,is_nap_inferred FROM sleep_sessions ORDER BY sleep_start_utc")
    stages_by_session = {r["source_record_id"]:r for r in query(con, "SELECT source_record_id,count(*) n,sum(duration_minutes) total_minutes,sum(CASE WHEN stage='awake' THEN duration_minutes ELSE 0 END) awake_minutes,min(start_timestamp_utc) first,max(end_timestamp_utc) last FROM sleep_stages GROUP BY source_record_id")}
    sleep["session_counts"]={"total":len(sessions),"with_stages":sum(bool(s["has_stages"]) for s in sessions),"with_rem":sum(bool(s["has_rem"]) for s in sessions),"naps":sum(bool(s["is_nap_inferred"]) for s in sessions),"dated":sum(s["local_date"] is not None for s in sessions)}
    sleep["field_nonnull"]={k:sum(s[k] is not None for s in sessions) for k in ("sleep_start_utc","sleep_end_utc","duration_minutes","deep_minutes","light_minutes","rem_minutes","awake_minutes","sleep_score","sleep_efficiency","avg_hr","avg_spo2","avg_respiratory_rate","breathing_quality","awake_count")}
    sleep["stage_minus_session_minutes"] = quantiles([stages_by_session[s["source_record_id"]]["total_minutes"]-(s["sleep_end_utc"]-s["sleep_start_utc"])/60 for s in sessions if s["source_record_id"] in stages_by_session and s["sleep_start_utc"] is not None and s["sleep_end_utc"] is not None])
    sleep["reported_tst_minus_stage_sleep_minutes"] = quantiles([(s["deep_minutes"] or 0)+(s["light_minutes"] or 0)+(s["rem_minutes"] or 0)-(stages_by_session[s["source_record_id"]]["total_minutes"]-stages_by_session[s["source_record_id"]]["awake_minutes"]) for s in sessions if s["source_record_id"] in stages_by_session and s["deep_minutes"] is not None and s["light_minutes"] is not None])
    sleep["duration_minus_clock_minutes"] = quantiles([s["duration_minutes"]-(s["sleep_end_utc"]-s["sleep_start_utc"])/60 for s in sessions if s["duration_minutes"] is not None and s["sleep_start_utc"] is not None and s["sleep_end_utc"] is not None])
    sleep["invalid_sessions"]={"negative_clock":sum(s["sleep_start_utc"] is not None and s["sleep_end_utc"] is not None and s["sleep_end_utc"]<s["sleep_start_utc"] for s in sessions),"negative_reported_duration":sum(s["duration_minutes"] is not None and s["duration_minutes"]<0 for s in sessions)}
    sleep["overlapping_sessions"] = sum(a["sleep_end_utc"] is not None and b["sleep_start_utc"] is not None and a["sleep_end_utc"]>b["sleep_start_utc"] for a,b in zip(sessions,sessions[1:]))
    sleep["stage_duplicates"] = one(con, "SELECT count(*) duplicate_groups,sum(n-1) excess_rows FROM (SELECT source_record_id,start_timestamp_utc,end_timestamp_utc,stage,count(*) n FROM sleep_stages GROUP BY 1,2,3,4 HAVING n>1)")
    sleep["invalid_stages"] = one(con, "SELECT sum(st.end_timestamp_utc<st.start_timestamp_utc) negative,sum(st.start_timestamp_utc<s.sleep_start_utc OR st.end_timestamp_utc>s.sleep_end_utc) outside_session,sum(st.duration_minutes<0) negative_duration FROM sleep_stages st JOIN sleep_sessions s USING(source_record_id)")
    sleep["stage_types"] = query(con, "SELECT stage,raw_state,count(*) n,min(duration_minutes) min_duration,max(duration_minutes) max_duration FROM sleep_stages GROUP BY stage,raw_state ORDER BY n DESC")

    result["spo2"] = {"by_kind":query(con,"SELECT kind,count(*) n,count(distinct local_date) days,min(value) min,max(value) max FROM spo2 GROUP BY kind ORDER BY n DESC"),"ranges":one(con,"SELECT sum(value<0 OR value>100) impossible,sum(value<70) below70,sum(value=0) zeros FROM spo2"),"daily_counts":query(con,"SELECT local_date,count(*) n,min(value) min,max(value) max FROM spo2 GROUP BY local_date ORDER BY local_date")}
    result["stress"] = {"by_kind":query(con,"SELECT kind,count(*) n,count(distinct local_date) days,min(value) min,max(value) max FROM stress GROUP BY kind ORDER BY n DESC"),"daily_counts":query(con,"SELECT local_date,count(*) n,min(value) min,max(value) max FROM stress GROUP BY local_date ORDER BY local_date")}
    result["daily_summary_nonnull"] = one(con,"SELECT " + ",".join(f"sum({ident(c['name'])} IS NOT NULL) AS {ident(c['name'])}" for c in query(con,"PRAGMA table_info(daily_summary)") if c["name"] not in ("local_date","updated_at")) + " FROM daily_summary")
    result["workouts"] = query(con,"SELECT workout_type,sport_type,count(*) n,count(duration_seconds) with_duration,count(avg_hr) with_avg_hr,count(training_load) with_training_load FROM workouts GROUP BY workout_type,sport_type ORDER BY n DESC")
    result["raw_key_matches"] = {}
    matches = collections.defaultdict(lambda: {"count":0,"types":collections.Counter(),"numeric_min":None,"numeric_max":None})
    bad_json = 0
    for source_table, record, payload in con.execute("SELECT source_table,record_json,value_json FROM raw_records"):
        for origin,text in (("record",record),("value",payload)):
            if text is None:
                continue
            try:
                obj=json.loads(text)
            except (ValueError,TypeError):
                bad_json+=1
                continue
            for path,value in walk_keys(obj):
                if not KEY_PATTERN.search(path):
                    continue
                item=matches[(source_table,origin+"."+path)]
                item["count"]+=1
                typ="null" if value is None else type(value).__name__
                item["types"][typ]+=1
                if isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value):
                    item["numeric_min"]=value if item["numeric_min"] is None else min(item["numeric_min"],value)
                    item["numeric_max"]=value if item["numeric_max"] is None else max(item["numeric_max"],value)
    result["raw_key_matches"]={f"{t}:{p}":dict(v,types=dict(v["types"])) for (t,p),v in sorted(matches.items())}
    result["raw_bad_json"] = bad_json
    result["file_after"] = file_signature(db_path)
    result["stable_during_scan"] = result["file_before"] == result["file_after"]
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--db",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    uri="file:"+str(args.db.resolve()).replace(" ","%20")+"?mode=ro&immutable=1"
    con=sqlite3.connect(uri,uri=True)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    result=profile(con,args.db)
    con.close()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+"\n")
    print(f"tables={len(result['tables'])} stable={result['stable_during_scan']} output={args.output}")


if __name__=="__main__":
    main()
