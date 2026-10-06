#!/usr/bin/env python3
"""Read-only, score-free input-coverage checks for Mi Fitness analytics research."""

import argparse
import collections
import datetime as dt
import json
import sqlite3
import statistics
from pathlib import Path


def coverage(dates, first, last):
    sorted_dates=sorted(set(dates))
    total=(dt.date.fromisoformat(last)-dt.date.fromisoformat(first)).days+1
    return {"usable_days":len(sorted_dates),"calendar_days":total,"percent":round(100*len(sorted_dates)/total,1),"first":sorted_dates[0] if sorted_dates else None,"last":sorted_dates[-1] if sorted_dates else None}


def prior_count(dates, need, lookback=None):
    """Count days with sufficient earlier observations; never calculate scores."""
    ordered=sorted(set(dates))
    good=[]
    for day in ordered:
        previous=[p for p in ordered if p<day and (lookback is None or (dt.date.fromisoformat(day)-dt.date.fromisoformat(p)).days<=lookback)]
        if len(previous)>=need:
            good.append(day)
    return good


def q(values):
    if not values:return {}
    x=sorted(values)
    return {str(k):x[round((len(x)-1)*k/100)] for k in (10,25,50,75,90,95,99)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    uri='file:'+str(a.db.resolve()).replace(' ','%20')+'?mode=ro&immutable=1'
    c=sqlite3.connect(uri,uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON')
    rows=[dict(x) for x in c.execute('SELECT * FROM daily_summary ORDER BY local_date')]
    first,last=rows[0]['local_date'],rows[-1]['local_date']
    fields=('steps','distance','step_calories','total_calories','activity_duration_minutes','standing_count','resting_hr','avg_hr','min_hr','max_hr','abnormal_hr_count','avg_spo2','min_spo2','max_spo2','avg_stress','sleep_total_minutes','deep_sleep_minutes','light_sleep_minutes','rem_sleep_minutes','awake_minutes','nap_minutes','sleep_score','avg_respiratory_rate','breathing_quality','vitality')
    dates={f:{r['local_date'] for r in rows if r[f] is not None and not (f in ('avg_spo2','avg_respiratory_rate','resting_hr') and r[f]<=0)} for f in fields}
    dates['hr_samples']={x[0] for x in c.execute('SELECT DISTINCT local_date FROM heart_rate WHERE local_date IS NOT NULL')}
    dates['spo2_samples']={x[0] for x in c.execute('SELECT DISTINCT local_date FROM spo2 WHERE local_date IS NOT NULL')}
    dates['stress_samples']={x[0] for x in c.execute('SELECT DISTINCT local_date FROM stress WHERE local_date IS NOT NULL')}
    dates['event_hr']={x[0] for x in c.execute('SELECT DISTINCT local_date FROM heart_rate_events WHERE local_date IS NOT NULL')}
    dates['workout']={x[0] for x in c.execute('SELECT DISTINCT local_date FROM workouts WHERE local_date IS NOT NULL')}
    dates['night_respiration']={x[0] for x in c.execute('SELECT DISTINCT local_date FROM sleep_sessions WHERE avg_respiratory_rate>0')}
    dates['night_efficiency']={x[0] for x in c.execute('SELECT DISTINCT local_date FROM sleep_sessions WHERE sleep_efficiency>0')}
    dates['main_sleep']={x[0] for x in c.execute('SELECT DISTINCT local_date FROM sleep_sessions WHERE is_nap_inferred=0 AND sleep_start_utc IS NOT NULL AND sleep_end_utc IS NOT NULL')}
    dates['stage_sleep']={x[0] for x in c.execute('SELECT DISTINCT local_date FROM sleep_sessions WHERE has_stages=1 AND is_nap_inferred=0')}
    dates['main_sleep_score']=dates['sleep_score'] & dates['main_sleep']
    combos={
      'rhr_sleep':dates['resting_hr']&dates['main_sleep'],
      'rhr_sleep_score':dates['resting_hr']&dates['main_sleep_score'],
      'rhr_sleep_spo2':dates['resting_hr']&dates['main_sleep']&dates['spo2_samples'],
      'rhr_respiration_sleep':dates['resting_hr']&dates['night_respiration']&dates['main_sleep'],
      'rhr_sleep_steps':dates['resting_hr']&dates['main_sleep']&dates['steps'],
      'stress_sleep':dates['avg_stress']&dates['main_sleep'],
      'steps_sleep':dates['steps']&dates['main_sleep'],
      'hr_rhr_steps':dates['hr_samples']&dates['resting_hr']&dates['steps'],
      'hr_rhr_sleep':dates['hr_samples']&dates['resting_hr']&dates['main_sleep'],
      'spo2_rhr':dates['spo2_samples']&dates['resting_hr'],
      'workout_rhr':dates['workout']&dates['resting_hr'],
    }
    night_rows=[]
    for s in c.execute('SELECT source_record_id,local_date,sleep_start_utc,sleep_end_utc,duration_minutes FROM sleep_sessions WHERE is_nap_inferred=0'):
        h=c.execute('SELECT count(*),count(distinct timestamp_utc/300),count(distinct timestamp_utc/60) FROM heart_rate WHERE timestamp_utc>=? AND timestamp_utc<?',(s['sleep_start_utc'],s['sleep_end_utc'])).fetchone()
        o=c.execute('SELECT count(*),count(distinct timestamp_utc/300) FROM spo2 WHERE timestamp_utc>=? AND timestamp_utc<?',(s['sleep_start_utc'],s['sleep_end_utc'])).fetchone()
        h_times=[x[0] for x in c.execute('SELECT DISTINCT timestamp_utc/60 FROM heart_rate WHERE timestamp_utc>=? AND timestamp_utc<? ORDER BY timestamp_utc/60',(s['sleep_start_utc'],s['sleep_end_utc']))]
        left=max30=0
        for right,minute in enumerate(h_times):
            while minute-h_times[left]>=30:
                left+=1
            max30=max(max30,right-left+1)
        clock_minutes=(s['sleep_end_utc']-s['sleep_start_utc'])/60 if s['sleep_start_utc'] is not None and s['sleep_end_utc'] is not None else None
        night_rows.append({'day':s['local_date'],'clock_minutes':clock_minutes,'hr_n':h[0],'hr_bins':h[1],'hr_minutes':h[2],'hr_max30':max30,'spo2_n':o[0],'spo2_bins':o[1]})
    # NOOP's qualified 5-min bin: at least five >=25 bpm readings.
    qualified={x[0] for x in c.execute('''
      SELECT s.local_date FROM sleep_sessions s JOIN heart_rate h
      ON h.timestamp_utc>=s.sleep_start_utc AND h.timestamp_utc<s.sleep_end_utc
      WHERE s.is_nap_inferred=0 AND h.bpm>=25
      GROUP BY s.source_record_id,h.timestamp_utc/300 HAVING count(*)>=5
    ''')}
    dates['night_hr_any']={n['day'] for n in night_rows if n['hr_n']>0}
    dates['night_hr_qualified5']=qualified
    dates['night_spo2_any']={n['day'] for n in night_rows if n['spo2_n']>0}
    dates['night_spo2_20']={n['day'] for n in night_rows if n['spo2_n']>=20}
    dates['night_hr_50pct_minutes']={n['day'] for n in night_rows if n['clock_minutes'] and n['hr_minutes']>=.5*n['clock_minutes']}
    dates['night_hr_30min90pct']={n['day'] for n in night_rows if n['hr_max30']>=27}
    dates['night_spo2_50pct_5min']={n['day'] for n in night_rows if n['clock_minutes'] and n['spo2_bins']>=.5*(n['clock_minutes']/5)}
    # Count actual sessions separately from dates for sleep denominators.
    raw_nights=len(night_rows)
    warmups={
      'rhr_prior5':prior_count(dates['resting_hr'],5),
      'rhr_prior7':prior_count(dates['resting_hr'],7),
      'rhr_prior14':prior_count(dates['resting_hr'],14),
      'rhr_prior30':prior_count(dates['resting_hr'],30),
      'rhr_prior5_in30':prior_count(dates['resting_hr'],5,30),
      'rhr_prior7_in30':prior_count(dates['resting_hr'],7,30),
      'sleep_prior4':prior_count(dates['main_sleep'],4),
      'sleep_prior5_in14':prior_count(dates['main_sleep'],5,14),
      'sleep_prior7':prior_count(dates['main_sleep'],7),
      'sleep_prior14':prior_count(dates['main_sleep'],14),
      'sleep_prior30':prior_count(dates['main_sleep'],30),
      'spo2_prior5_in30':prior_count(dates['spo2_samples'],5,30),
      'resp_prior5_in30':prior_count(dates['night_respiration'],5,30),
      'resp_prior14':prior_count(dates['night_respiration'],14),
      'stress_prior5':prior_count(dates['avg_stress'],5),
      'steps_prior28':prior_count(dates['steps'],28),
      'steps_prior13_in28':prior_count(dates['steps'],13,28),
      'steps_prior84':prior_count(dates['steps'],84),
    }
    out={'db_path':str(a.db),'period':{'first':first,'last':last,'calendar_days':coverage(set(),first,last)['calendar_days']},
         'signals':{k:coverage(v,first,last) for k,v in dates.items()},
         'combinations':{k:coverage(v,first,last) for k,v in combos.items()},
         'warmups':{k:coverage(v,first,last) for k,v in warmups.items()},
         'sleep_nights_total':raw_nights,
         'nightly_hr_counts':q([n['hr_n'] for n in night_rows]),
         'nightly_spo2_counts':q([n['spo2_n'] for n in night_rows]),
         'nightly_hr_minute_coverage_percent':q([round(100*n['hr_minutes']/n['clock_minutes']) for n in night_rows if n['clock_minutes']]),
         'nightly_spo2_5min_coverage_percent':q([round(100*n['spo2_bins']/(n['clock_minutes']/5)) for n in night_rows if n['clock_minutes']]),
         'raw_input_coverage':{},'warmed_output_coverage':{}}
    out['raw_input_coverage']['rhr_sleep']=out['combinations']['rhr_sleep']
    out['warmed_output_coverage']['rhr_sleep_rhr_prior5']=coverage(combos['rhr_sleep']&set(warmups['rhr_prior5']),first,last)
    out['warmed_output_coverage']['rhr_resp_sleep_rhr_prior5_resp_prior5']=coverage(combos['rhr_respiration_sleep']&set(warmups['rhr_prior5'])&set(warmups['resp_prior5_in30']),first,last)
    rrsp=dict(c.execute('SELECT local_date,avg(avg_respiratory_rate) FROM sleep_sessions WHERE avg_respiratory_rate>0 AND is_nap_inferred=0 GROUP BY local_date'))
    rhr={r['local_date']:r['resting_hr'] for r in rows if r['resting_hr'] is not None and r['resting_hr']>0}
    readiness_eligible=[]
    for day in sorted(set(rhr)&set(rrsp)):
        hrbase=[v for d,v in rhr.items() if d<day]
        rrbase=[v for d,v in rrsp.items() if d<day]
        if len(hrbase)>=14 and len(rrbase)>=14 and statistics.stdev(hrbase)>=1 and statistics.stdev(rrbase)>0:
            readiness_eligible.append(day)
    out['warmed_output_coverage']['openstrap_rhr_rrsp_14prior_quality']=coverage(readiness_eligible,first,last)
    c.close();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(f"coverage output={a.output} nights={raw_nights}")

if __name__=='__main__':main()
