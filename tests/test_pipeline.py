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
