import gzip,json
import job_watcher as jw
def test_title_rule():
    assert jw.in_role('Senior Financial Analyst')
    assert jw.in_role('FP&A Analyst')
    assert jw.in_role('Cost Analyst')
    assert not jw.in_role('Software Engineer')
def test_normalize():
    s={'name':'Test','employer':'Test','host':'test.wd1.myworkdayjobs.com','site':'External'}
    rows=jw.normalize(s,{'jobPostings':[{'title':'Financial Analyst','externalPath':'/job/123','locationsText':'Chicago'}]})
    assert rows[0]['posting_id']=='test:/job/123'
    assert rows[0]['in_role']=='true'
def test_lifecycle(tmp_path,monkeypatch):
    monkeypatch.setattr(jw,'DATA',tmp_path/'data')
    monkeypatch.setattr(jw,'sources',lambda:[{'name':'Test','employer':'Test','host':'x','site':'External'}])
    def snapshot(day,jobs):
        p=jw.DATA/'raw'/day/'test.json.gz';p.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(p,'wt') as f:json.dump({'jobPostings':[{'title':'Financial Analyst','externalPath':'/job/'+str(j)} for j in jobs]},f)
    snapshot('2026-11-01',[1]);r,d=jw.build();assert r[0]['first_run']=='true'
    snapshot('2026-11-03',[]);r,d=jw.build();assert r[0]['removed_date']=='2026-11-03'
    snapshot('2026-11-04',[1]);r,d=jw.build();assert r[0]['status']=='open' and r[0]['first_seen']=='2026-11-01'
    old=(jw.DATA/'history.csv').read_bytes();jw.build();assert old==(jw.DATA/'history.csv').read_bytes()

def test_workday_pagination():
    class Response:
        def __init__(self, jobs):
            self.jobs = jobs
        def raise_for_status(self):
            pass
        def json(self):
            return {'total': 45, 'jobPostings': self.jobs}
    class Session:
        def __init__(self):
            self.offsets = []
        def post(self, url, json, headers, timeout):
            offset = json['offset']
            self.offsets.append(offset)
            return Response([{'title': 'Analyst', 'externalPath': '/job/'+str(i)}
                             for i in range(offset, min(offset+20,45))])
    session=Session()
    s={'host':'example.wd5.myworkdayjobs.com','tenant':'example','site':'External'}
    result=jw.get_workday(session,s)
    assert len(result['jobPostings']) == 45
    assert session.offsets == [0,20,40]

def test_failed_source_does_not_count_as_success(tmp_path, monkeypatch):
    monkeypatch.setattr(jw,'DATA',tmp_path/'data')
    monkeypatch.setattr(jw,'sources',lambda:[{'name':'Broken','employer':'Broken',
        'ats':'workday','enabled':True,'host':'example.com','tenant':'x','site':'Y'}])
    def fail(_session, _source):
        raise RuntimeError('HTTP 502')
    monkeypatch.setattr(jw,'get_workday',fail)
    report=jw.collect('2026-11-04',session=object())
    assert report[0]['ok'] is False
    assert not list((jw.DATA/'raw').glob('*/*.json.gz'))


def test_pipeline_scripts_have_valid_python_syntax():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for filename in ['job_watcher.py', 'commit_snapshot.py', 'issue_report.py']:
        source = (root / filename).read_text(encoding='utf-8')
        compile(source, str(root / filename), 'exec')


def test_rate_limited_sources_are_deferred(tmp_path, monkeypatch):
    monkeypatch.setattr(jw, 'DATA', tmp_path / 'data')
    monkeypatch.setattr(jw, 'sources', lambda: [
        {'name': name, 'enabled': True, 'ats': 'workday'}
        for name in ('First', 'Second', 'Third')
    ])
    class Session:
        rate_limit_stop = None
    session = Session()
    calls = []
    def fail(client, source):
        calls.append(source['name'])
        client.rate_limit_stop = 'HTTP 429: rate limited'
        raise jw.RateLimited(client.rate_limit_stop)
    monkeypatch.setattr(jw, 'get_workday', fail)
    result = jw.collect('2026-11-17', session)
    assert calls == ['First']
    assert [s['error_code'] for s in result] == ['rate_limited', 'deferred', 'deferred']
    assert [s['attempted'] for s in result] == [True, False, False]
    assert not list((jw.DATA / 'raw').glob('*/*.json.gz'))


def test_zero_success_publishes_only_diagnostics(tmp_path, monkeypatch):
    import commit_snapshot as cs
    from types import SimpleNamespace
    data = tmp_path / 'data'
    raw = data / 'raw' / '2026-11-17'
    raw.mkdir(parents=True)
    current = {'run_time': '2026-11-17T12:00:00Z',
               'sources': [{'name': 'Test', 'ok': False, 'count': 0}]}
    previous = {'run_time': '2026-11-16T12:00:00Z', 'days_with_success': 13}
    (data / 'status.json').write_text(json.dumps(current))
    (data / 'history.csv').write_text('unchanged')
    monkeypatch.setattr(cs, 'DATA', data)
    calls = []
    def git(*args, **kwargs):
        calls.append(args)
        if args[:2] == ('reset', '--hard'):
            (data / 'status.json').write_text(json.dumps(previous))
        return SimpleNamespace(returncode=1 if args[0]=='diff' else 0, stderr='')
    monkeypatch.setattr(cs, 'git', git)
    cs.publish()
    assert json.loads((data / 'attempt.json').read_text()) == current
    assert json.loads((data / 'status.json').read_text()) == previous
    assert (data / 'history.csv').read_text() == 'unchanged'
    assert [args for args in calls if args[0]=='add'] == [('add','data/attempt.json')]


def test_provider_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(jw,'DATA',tmp_path/'data')
    cfg=[{'name':'W','employer':'W','ats':'workday','enabled':True},
         {'name':'G','employer':'G','ats':'greenhouse','enabled':True},
         {'name':'S','employer':'S','ats':'smartrecruiters','enabled':True}]
    monkeypatch.setattr(jw,'sources',lambda:cfg)
    class Client:
        rate_limit_stop=None
    clients={}
    def make(provider='workday'):
        clients[provider]=Client()
        return clients[provider]
    monkeypatch.setattr(jw,'make_session',make)
    def blocked(client,source):
        client.rate_limit_stop='HTTP 429'
        raise jw.RateLimited('HTTP 429')
    monkeypatch.setattr(jw,'get_greenhouse',blocked)
    monkeypatch.setattr(jw,'get_smartrecruiters',lambda c,s:{'pages':[{'content':[{'id':'1','name':'Analyst'}]}]})
    monkeypatch.setattr(jw,'get_workday',lambda c,s:{'jobPostings':[{'title':'Analyst','externalPath':'/job/1'}]})
    result={r['name']:r for r in jw.collect('2026-11-19')}
    assert not result['G']['ok'] and result['W']['ok'] and result['S']['ok']
    assert len(clients)==3

def test_public_ats_normalization():
    g={'name':'G','employer':'G','ats':'greenhouse','board':'g'}
    raw={'jobs':[{'id':123,'title':'Financial Analyst','location':{'name':'Chicago'},'absolute_url':'https://example.com/job'}]}
    assert jw.normalize(g,raw)[0]['posting_id']=='g:123'
    s={'name':'S','employer':'S','ats':'smartrecruiters','board':'S'}
    raw={'pages':[{'content':[{'id':'abc','name':'Cost Analyst','releasedDate':'2026-11-19T12:00:00Z','location':{'city':'Dallas'}}]}]}
    assert jw.normalize(s,raw)[0]['posted_date']=='2026-11-19'


def test_every_employer_has_fallback_and_isolation_config():
    configs=jw.sources()
    assert len(configs)>=20
    assert len({c['name'] for c in configs})==len(configs)
    assert all(c.get('fallback',{}).get('provider')=='headcount' for c in configs)
    assert all(c['fallback'].get('cache')=='last_successful_snapshot' for c in configs)
    assert all(c['fallback'].get('requires_authorization') is True for c in configs)
    assert {'workday','greenhouse','smartrecruiters'}<=set(c['ats'] for c in configs)

def test_smartrecruiters_incomplete_page_refused():
    class Response:
        def raise_for_status(self): pass
        def json(self):return {'content':[],'totalFound':1,'offset':0}
    class Session:
        def get(self,*args,**kwargs):return Response()
    import pytest
    with pytest.raises(ValueError,match='Incomplete'):
        jw.get_smartrecruiters(Session(),{'board':'Example'})

def test_backups_never_count_as_fresh_snapshots(tmp_path):
    import backup_sources as backup
    root=tmp_path/'data'
    root.mkdir()
    configs=[{'name':'Example','employer':'Example','ticker':'EX',
              'ats':'workday','fallback':{'company_query':'Example'}}]
    statuses=[{'name':'Example','ok':False,'count':0}]
    import os
    key=os.environ.pop('HEADCOUNT_API_KEY',None)
    enabled=os.environ.pop('ENABLE_LICENSED_BACKUP',None)
    try:
        r=backup.collect_backups(root,configs,statuses,'2026-11-22',jw.slug,
                                 lambda provider: (_ for _ in ()).throw(AssertionError('network called')))
        assert r['sources'][0]['secondary']['state']=='authorization_required'
        assert r['sources'][0]['cache']['state']=='no_snapshot'
        assert not list(root.glob('raw/*/*.json.gz'))
    finally:
        if key is not None:os.environ['HEADCOUNT_API_KEY']=key
        if enabled is not None:os.environ['ENABLE_LICENSED_BACKUP']=enabled
