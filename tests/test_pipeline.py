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
