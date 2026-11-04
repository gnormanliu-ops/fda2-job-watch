"""Daily JSON ATS collection and deterministic history reconstruction."""
import argparse,csv,gzip,json,re
from datetime import datetime,timezone
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
COLS='posting_id source source_id employer title location department posted_date url in_role first_run first_seen last_seen status removed_date'.split()
ROLE=re.compile(r'\b(financial?\s+(?:planning|analyst|analytics|data)|fp\s*&\s*a|finance\s+(?:analyst|manager|associate)|cost\s+analyst|business\s+analyst|data\s+analyst|risk\s+analyst|investment\s+analyst|operations?\s+analyst|treasury\s+analyst|controller)\b',re.I)
def in_role(t):return bool(ROLE.search(t or ''))
def slug(t):return re.sub('[^a-z0-9]+','-',t.lower()).strip('-')
def sources():return json.loads((ROOT/'sources.json').read_text())
def get_workday(session,s):
    url=f"https://{s['host']}/wday/cxs/{s['tenant']}/{s['site']}/jobs"
    jobs=[];offset=0
    while True:
        response=session.post(url,json={'limit':20,'offset':offset,'searchText':s.get('search_term',''),'appliedFacets':{}},headers={'Accept':'application/json','User-Agent':'FDA-Job-Watcher/1.0'},timeout=35)
        response.raise_for_status();payload=response.json()
        batch=payload.get('jobPostings')
        if not isinstance(batch,list):raise ValueError('Missing jobPostings')
        total=payload.get('total',len(batch))
        if total>5000 and not s.get('search_term'):raise ValueError('Over 5000 jobs: configure search_term')
        jobs+=batch
        if len(jobs)>=total:break
        if not batch:raise ValueError('Incomplete pagination')
        offset+=len(batch)
    return {'jobPostings':jobs,'total':len(jobs)}
def collect(day,session=None):
    session=session or requests.Session();p=DATA/'raw'/day;p.mkdir(parents=True,exist_ok=True);result=[]
    for s in sources():
        dest=p/(slug(s['name'])+'.json.gz');dest.unlink(missing_ok=True)
        r={'name':s['name'],'ok':False,'count':0}
        if s.get('enabled'):
            try:
                if s.get('ats')!='workday':raise ValueError('Adapter unavailable')
                raw=get_workday(session,s)
                with gzip.open(dest,'wt',encoding='utf8') as f:json.dump(raw,f)
                r.update(ok=True,count=len(raw['jobPostings']))
            except Exception as e:r['error']=str(e)[:180];dest.unlink(missing_ok=True)
        else:r['error']='Unverified source'
        result.append(r)
    return result
def normalize(s,raw):
    result=[]
    for p in raw.get('jobPostings',[]):
        ext=str(p.get('externalPath') or '')
        ident=str(p.get('id') or ext)
        if not ident:continue
        posted=str(p.get('postedOn') or '')
        result.append(dict(posting_id=slug(s['name'])+':'+ident,source=slug(s['name']),source_id=ident,employer=s['employer'],title=p.get('title') or '',location=p.get('locationsText') or p.get('location') or '',department=p.get('department') or '',posted_date=posted if re.fullmatch(r'\d{4}-\d{2}-\d{2}',posted) else '',url='https://'+s['host']+'/'+s['site']+ext if ext.startswith('/') else '',in_role=str(in_role(p.get('title'))).lower()))
    return result
def build():
    DATA.mkdir(exist_ok=True);by_source={slug(s['name']):s for s in sources()};history={};first={};dates=set()
    for path in sorted((DATA/'raw').glob('*/*.json.gz')):
        day=path.parent.name;key=path.name.removesuffix('.json.gz')
        if key not in by_source or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):continue
        with gzip.open(path,'rt',encoding='utf8') as f:raw=json.load(f)
        dates.add(day);first.setdefault(key,day);seen=set()
        for row in normalize(by_source[key],raw):
            id=row['posting_id']
            if id in seen:continue
            seen.add(id)
            if id not in history:history[id]={**row,'first_run':str(day==first[key]).lower(),'first_seen':day,'last_seen':day,'status':'open','removed_date':''}
            else:
                for k in ['title','location','department','posted_date','url','in_role']:history[id][k]=row[k]
                history[id].update(last_seen=day,status='open',removed_date='')
        for id,r in history.items():
            if r['source']==key and r['status']=='open' and id not in seen:r.update(status='removed',removed_date=day)
    with (DATA/'history.csv').open('w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=COLS);writer.writeheader();writer.writerows(history[k] for k in sorted(history))
    return list(history.values()),sorted(dates)
def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['run','build']);a=p.parse_args()
    now=datetime.now(timezone.utc);today=now.date().isoformat()
    old=DATA/'status.json';results=json.loads(old.read_text()).get('sources',[]) if old.exists() else []
    if a.command=='run':results=collect(today)
    rows,days=build()
    stat=dict(run_time=now.isoformat().replace('+00:00','Z'),first_run_date=days[0] if days else '',days_with_success=len(days),open=sum(r['status']=='open' for r in rows),new_today=sum(r['first_seen']==today and r['first_run']=='false' for r in rows),removed_today=sum(r['removed_date']==today for r in rows),sources=results)
    (DATA/'status.json').write_text(json.dumps(stat,indent=2)+'\n')
    print('Snapshots:',len(days),'open:',stat['open'],'working sources:',sum(s['ok'] for s in results))
if __name__=='__main__':main()
