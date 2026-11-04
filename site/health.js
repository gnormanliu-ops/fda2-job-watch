/* Status dashboard: UTC schedule, actual run and source coverage. */
const RUN_HOUR=10, RUN_MINUTE=19; // .github/workflows/daily.yml (UTC)
function utcNextSchedule(now=new Date()){
  const d=new Date(now);
  d.setUTCHours(RUN_HOUR,RUN_MINUTE,0,0);
  if(d<=now)d.setUTCDate(d.getUTCDate()+1);
  return d;
}
function fmtTime(x,zone){
  if(!x||!Number.isFinite(new Date(x).getTime()))return 'No successful report yet';
  return new Intl.DateTimeFormat('en-US',{timeZone:zone,dateStyle:'medium',timeStyle:'short',timeZoneName:'short'}).format(new Date(x));
}
function sourceHealth(s){
  if(!s.ok)return {label:s.error==='Unverified source'?'Not configured':'Failed',kind:'bad',detail:s.error||'No snapshot returned'};
  if(s.count===0)return {label:'Empty',kind:'warn',detail:'Request succeeded, but no postings returned'};
  if(s.count===40)return {label:'Review (40)',kind:'warn',detail:'Exactly 40 jobs returned; verify pagination and coverage'};
  return {label:'OK',kind:'good',detail:'JSON returned; not an independent audit of completeness'};
}
function overall(s){
  const list=s.sources||[];
  const successful=list.filter(x=>x.ok).length;
  const failed=list.length-successful;
  const suspicious=list.filter(x=>x.ok&&(x.count===0||x.count===40)).length;
  const last=new Date(s.run_time);
  const ageH=Number.isFinite(last.getTime())?(Date.now()-last.getTime())/3600000:Infinity;
  let kind=failed||suspicious?'warn':'good',label=failed||suspicious?'Partial coverage':'All sources reported OK';
  if(!successful){kind='bad';label='No working sources'}
  if(ageH>36){kind='bad';label='Stale data'}
  return {kind,label,successful,failed,suspicious,ageH};
}
function badge(text,kind){return '<span class="health-pill health-'+kind+'">'+esc(text)+'</span>'}
async function renderDashboard(){
 try{
  const [s,rows]=await Promise.all([load('status.json'),load('history.csv')]);
  const latest=(s.run_time||'').slice(0,10), health=overall(s);
  document.getElementById('run').textContent='Last recorded run: '+fmtTime(s.run_time,'UTC')+' · '+fmtTime(s.run_time,'America/Chicago');
  document.getElementById('cards').innerHTML=[
   ['Successful UTC days',s.days_with_success||0],['Open postings',s.open||0],['New today',s.new_today||0],['Removed today',s.removed_today||0]
  ].map(x=>'<div class="card"><div class="number">'+esc(x[1])+'</div>'+esc(x[0])+'</div>').join('');
  const next=utcNextSchedule();
  document.getElementById('update-health').innerHTML=
   '<div class="health-grid">'+
   '<div><div class="muted">Scheduled automatic collection</div><strong>Daily at 10:19 UTC</strong><p class="muted">4:19 AM CST / 5:19 AM CDT · GitHub Actions may start late.</p></div>'+
   '<div><div class="muted">Next scheduled start (estimated)</div><strong>'+esc(fmtTime(next,'America/Chicago'))+'</strong><p class="muted">'+esc(fmtTime(next,'UTC'))+'</p></div>'+
   '<div><div class="muted">Latest run recorded</div><strong>'+esc(fmtTime(s.run_time,'America/Chicago'))+'</strong><p class="muted">'+esc(fmtTime(s.run_time,'UTC'))+'</p></div>'+
   '<div><div class="muted">Data health</div>'+badge(health.label,health.kind)+'<p class="muted">'+health.successful+' / '+(s.sources||[]).length+' sources successful; '+health.failed+' failed/unconfigured; '+health.suspicious+' require coverage review.</p></div>'+
   '</div><p class="muted">Health uses last recorded run time, success flags, and suspicious counts. It does not verify whether an employer listed every job. Updated automatically when you open this page; refresh to check a new run.</p>';
  const list=s.sources||[];
  document.getElementById('sources').innerHTML=list.map(x=>{let st=sourceHealth(x);return '<tr><td>'+esc(x.name)+'</td><td>'+badge(st.label,st.kind)+'</td><td>'+esc(x.count)+'</td><td>'+esc(st.detail)+'</td></tr>'}).join('')||'<tr><td colspan="4">No collection report yet</td></tr>';
  document.getElementById('new').innerHTML=rows.filter(r=>r.first_seen===latest&&r.first_run==='false').map(r=>row(r)).join('')||'<tr><td colspan="5">No new postings detected. First-run positions are excluded.</td></tr>';
  document.getElementById('removed').innerHTML=rows.filter(r=>r.removed_date===latest).map(r=>row(r)).join('')||'<tr><td colspan="5">No removed postings detected.</td></tr>';
 }catch(e){document.getElementById('run').textContent='Data unavailable: '+e.message;document.getElementById('update-health').textContent='Unable to determine data health.'}
}
renderDashboard();
