"""Daily JSON ATS collection and deterministic history reconstruction."""
import argparse,csv,gzip,json,re,time
from datetime import datetime,timezone
from pathlib import Path
import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
COLS='posting_id source source_id employer title location department posted_date url in_role first_run first_seen last_seen status removed_date'.split()
ROLE=re.compile(r'\b(financial?\s+(?:planning|analyst|analytics|data)|fp\s*&\s*a|finance\s+(?:analyst|manager|associate)|cost\s+analyst|business\s+analyst|data\s+analyst|risk\s+analyst|investment\s+analyst|operations?\s+analyst|treasury\s+analyst|controller)\b',re.I)
def in_role(t):return bool(ROLE.search(t or ''))
def slug(t):return re.sub('[^a-z0-9]+','-',t.lower()).strip('-')
def sources():return json.loads((ROOT/'sources.json').read_text())
class RateLimited(RuntimeError):
    pass


class WorkdaySession(requests.Session):
    """One paced client per ATS provider; respect its cooldown independently."""
    MIN_INTERVAL = 1.0
    DEFAULT_COOLDOWN = 90.0
    MAX_INLINE_WAIT = 180.0

    def __init__(self, provider="workday"):
        super().__init__()
        self.provider = provider
        self.next_request = 0.0
        self.rate_limit_stop = None

    def request(self, method, url, **kwargs):
        if self.rate_limit_stop:
            raise RateLimited(self.rate_limit_stop)
        for attempt in range(2):
            pause = self.next_request - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            self.next_request = time.monotonic() + self.MIN_INTERVAL
            response = super().request(method, url, **kwargs)
            if response.status_code != 429:
                return response
            # Handle both delta-seconds and HTTP-date Retry-After values.
            try:
                delay = Retry().parse_retry_after(response.headers["Retry-After"])
            except (KeyError, ValueError, TypeError, requests.exceptions.InvalidHeader,
                    urllib3.exceptions.InvalidHeader):
                delay = self.DEFAULT_COOLDOWN
            delay = max(self.DEFAULT_COOLDOWN, delay)
            response.close()
            if attempt or delay > self.MAX_INLINE_WAIT:
                self.rate_limit_stop = (
                    f"HTTP 429: {self.provider} rate limited; remaining requests for this provider deferred "
                    f"to a later scheduled collection (Retry-After {delay:.0f}s)"
                )
                raise RateLimited(self.rate_limit_stop)
            print(f"HTTP 429: pausing {self.provider} requests for {delay:.0f}s", flush=True)
            self.next_request = time.monotonic() + delay
        raise AssertionError("unreachable")


def make_session(provider="workday"):
    session = WorkdaySession(provider)
    # Never let adapter-level retries bypass the shared 429 cooldown.
    retry = Retry(total=2, connect=2, read=1, status=0,
                  backoff_factor=2,
                  allowed_methods=frozenset(['POST', 'GET']),
                  respect_retry_after_header=False, raise_on_status=False)
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session

def get_workday(session,s):
    url=f"https://{s['host']}/wday/cxs/{s['tenant']}/{s['site']}/jobs"
    jobs=[];offset=0;page_size=20;seen_offsets=set()
    while True:
        response=session.post(url,json={'limit':page_size,'offset':offset,'searchText':s.get('search_term',''),'appliedFacets':{}},headers={'Accept':'application/json','User-Agent':'FDA-Job-Watcher/1.0'},timeout=35)
        response.raise_for_status();payload=response.json()
        batch=payload.get('jobPostings')
        if not isinstance(batch,list):raise ValueError('Missing jobPostings')
        total=payload.get('total',len(batch))
        if not isinstance(total,int) or total < 0: raise ValueError('Invalid total count')
        if offset in seen_offsets: raise ValueError('Repeated pagination offset')
        seen_offsets.add(offset)
        if total>5000 and not s.get('search_term'):raise ValueError('Over 5000 jobs: configure search_term')
        jobs+=batch
        if len(jobs)>=total:break
        if not batch:raise ValueError('Incomplete pagination')
        offset+=len(batch)
        if offset>10000:raise ValueError('Unexpected pagination beyond 10000 postings')
    return {'jobPostings':jobs,'total':len(jobs)}
def get_greenhouse(session,s):
    url=f"https://boards-api.greenhouse.io/v1/boards/{s['board']}/jobs"
    response=session.get(url,headers={'Accept':'application/json','User-Agent':'FDA-Job-Watcher/1.0'},timeout=35)
    response.raise_for_status()
    payload=response.json()
    jobs=payload.get('jobs')
    if not isinstance(jobs,list):raise ValueError('Missing Greenhouse jobs array')
    total=payload.get('meta',{}).get('total',len(jobs))
    if not isinstance(total,int) or total!=len(jobs):raise ValueError('Incomplete Greenhouse response')
    if any(not isinstance(j,dict) or not j.get('id') or not j.get('title') or not j.get('absolute_url') for j in jobs):
        raise ValueError('Invalid Greenhouse posting')
    if len({str(j['id']) for j in jobs})!=len(jobs):raise ValueError('Duplicate Greenhouse posting IDs')
    return payload


def get_smartrecruiters(session,s):
    url=f"https://api.smartrecruiters.com/v1/companies/{s['board']}/postings"
    pages=[];jobs=[];offset=0;seen=set();expected=None
    while True:
        response=session.get(url,params={'limit':100,'offset':offset},headers={'Accept':'application/json','User-Agent':'FDA-Job-Watcher/1.0'},timeout=35)
        response.raise_for_status()
        payload=response.json()
        batch=payload.get('content');total=payload.get('totalFound')
        if not isinstance(batch,list) or not isinstance(total,int) or total<0:
            raise ValueError('Invalid SmartRecruiters response')
        if expected is None:expected=total
        if total!=expected:raise ValueError('SmartRecruiters total changed during paging')
        if total>10000:raise ValueError('SmartRecruiters board exceeds safety limit')
        if payload.get('offset',offset)!=offset:raise ValueError('Unexpected SmartRecruiters offset')
        for job in batch:
            if not isinstance(job,dict) or not job.get('id') or not job.get('name'):
                raise ValueError('Invalid SmartRecruiters posting')
            key=str(job['id'])
            if key in seen:raise ValueError('Repeated SmartRecruiters posting ID')
            seen.add(key)
        pages.append(payload);jobs.extend(batch)
        if len(jobs)==total:break
        if not batch or len(jobs)>total:raise ValueError('Incomplete SmartRecruiters pagination')
        offset+=len(batch)
    return {'pages':pages,'totalFound':expected}


def raw_jobs(s,raw):
    provider=s.get('ats','workday')
    if provider=='greenhouse':return raw['jobs']
    if provider=='smartrecruiters':return [job for page in raw['pages'] for job in page['content']]
    if provider=='workday':return raw['jobPostings']
    raise ValueError('Unknown ATS: '+provider)


def collect(day,session=None):
    p=DATA/'raw'/day;p.mkdir(parents=True,exist_ok=True)
    result=[];clients={}
    adapters={'workday':get_workday,'greenhouse':get_greenhouse,'smartrecruiters':get_smartrecruiters}
    # New public GET APIs are collected first; Workday remains a separate circuit.
    priority={'greenhouse':0,'smartrecruiters':1,'workday':2}
    for s in sorted(sources(),key=lambda x:priority.get(x.get('ats'),3)):
        provider=s.get('ats','workday')
        dest=p/(slug(s['name'])+'.json.gz')
        r={'name':s['name'],'ats':provider,'ok':False,'count':0,'attempted':False}
        if not s.get('enabled'):
            r['error']='Unverified source';result.append(r);continue
        if provider not in adapters:
            r['error']='Adapter unavailable';result.append(r);continue
        if provider not in clients:
            clients[provider]=session if session is not None and provider=='workday' else make_session(provider)
        client=clients[provider]
        if getattr(client,'rate_limit_stop',None):
            r.update(error_code='deferred',error=f'Deferred after {provider} rate limit; no request sent')
            result.append(r);continue
        try:
            r['attempted']=True
            raw=adapters[provider](client,s)
            count=len(raw_jobs(s,raw))
            if s.get('candidate') and count==0 and not any((DATA/'raw').glob('*/'+dest.name)):
                raise ValueError('Unvalidated candidate returned zero jobs; no initial snapshot saved')
            temp=dest.with_suffix('.tmp')
            try:
                with gzip.open(temp,'wt',encoding='utf8') as fh:json.dump(raw,fh)
                temp.replace(dest)
            finally:
                temp.unlink(missing_ok=True)
            r.update(ok=True,count=count)
        except Exception as e:
            r['error']=str(e)[:300]
            if isinstance(e,RateLimited):r['error_code']='rate_limited'
        result.append(r)
    return result


def normalize(s,raw):
    result=[]
    provider=s.get('ats','workday')
    if provider!='workday':
        for job in raw_jobs(s,raw):
            ident=str(job['id'])
            loc=job.get('location') or {}
            if provider=='greenhouse':
                title=job.get('title','')
                location=loc.get('name','')
                url=job.get('absolute_url','')
                posted='' # updated_at is not the original published date
                department=', '.join(d.get('name','') for d in job.get('departments',[]) if isinstance(d,dict))
            else:
                title=job.get('name','')
                location=', '.join(str(loc[k]) for k in ('city','region','country') if loc.get(k))
                url=f"https://jobs.smartrecruiters.com/{s['board']}/{ident}"
                posted=str(job.get('releasedDate') or '')[:10]
                department=(job.get('department') or {}).get('label','')
            result.append(dict(posting_id=slug(s['name'])+':'+ident,source=slug(s['name']),source_id=ident,employer=s['employer'],
                title=title,location=location,department=department,posted_date=posted if re.fullmatch(r'\d{4}-\d{2}-\d{2}',posted) else '',
                url=url if url.startswith('https://') else '',in_role=str(in_role(title)).lower()))
        return result
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
    if a.command=='run':
        results=collect(today)
        from backup_sources import collect_backups
        backups=collect_backups(DATA,sources(),results,today,slug,make_session)
        (DATA/'backup_status.json').write_text(json.dumps(backups,indent=2)+'\n')
    rows,days=build()
    stat=dict(run_time=now.isoformat().replace('+00:00','Z'),first_run_date=days[0] if days else '',days_with_success=len(days),open=sum(r['status']=='open' for r in rows),new_today=sum(r['first_seen']==today and r['first_run']=='false' for r in rows),removed_today=sum(r['removed_date']==today for r in rows),sources=results)
    (DATA/'status.json').write_text(json.dumps(stat,indent=2)+'\n')
    print('Snapshots:',len(days),'open:',stat['open'],'working sources:',sum(s['ok'] for s in results))
if __name__=='__main__':main()
