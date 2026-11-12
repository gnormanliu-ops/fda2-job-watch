/* Data health: separate job collection reliability from coverage quality. */
const RUN_HOUR=10, RUN_MINUTE=19;
function utcNextSchedule(now=new Date()){
 const d=new Date(now);d.setUTCHours(RUN_HOUR,RUN_MINUTE,0,0);
 if(d<=now)d.setUTCDate(d.getUTCDate()+1);return d;
}
function fmtTime(x,zone){
 const d=new Date(x);
 if(!x||!Number.isFinite(d.getTime()))return 'Not available';
 return new Intl.DateTimeFormat('en-US',{timeZone:zone,year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(d);
}
function sourceHealth(s){
 if(s.error==='Unverified source')return {label:'Not configured',kind:'neutral',detail:'No verified JSON interface configured'};
 if(!s.ok)return {label:'Failed',kind:'bad',detail:s.error||'No snapshot returned'};
 if(s.count===0)return {label:'Empty response',kind:'warn',detail:'JSON request succeeded but contained no postings; investigate'};
 if(s.count===40)return {label:'OK · scope review',kind:'warn',detail:'JSON request succeeded. Exactly 40 returned; check that the board is not capped'};
 return {label:'OK',kind:'good',detail:'JSON snapshot saved; completeness not independently verified'};
}
function healthSummary(status,rows){
 const list=status.sources||[];
 const configured=list.filter(s=>s.error!=='Unverified source');
 const working=configured.filter(s=>s.ok);
 const broken=configured.filter(s=>!s.ok);
 const unconfigured=list.length-configured.length;
 const review=working.filter(s=>s.count===40||s.count===0).length;
 const dt=Date.parse(status.run_time||'');
 const ageHours=Number.isFinite(dt)?(Date.now()-dt)/3600000:Infinity;
 const rowsOpen=rows.filter(r=>r.status==='open').length;
 const consistent=rowsOpen===Number(status.open);
 const offline=Object.values(window.jobDataOrigin||{}).some(x=>x==='cache');
 let state='good',label='Collection operational';
 if(broken.length){state='warn';label='Collection degraded'}
 if(!working.length||ageHours>36||!consistent){state='bad';label=!consistent?'Data files disagree':ageHours>36?'Data update overdue':'No working sources'}
 if(offline){state='warn';label='Offline / cached data'}
 return {state,label,list,configured:configured.length,working:working.length,broken:broken.length,unconfigured,review,ageHours,consistent,rowsOpen,offline};
}
function boardDetails(config){
 if(!config||!config.enabled||config.ats!=='workday'||!config.host||!config.site||!config.tenant)return {board:'—',scope:'Not configured'};
 // Construct links exclusively from our version-controlled source registry.
 if(!/^[a-z0-9.-]+\\.myworkdayjobs\\.com$/i.test(config.host))return {board:'Invalid host',scope:'Review source config'};
 const base='https://'+config.host;
 const board=base+'/'+encodeURIComponent(config.site);
 const api=base+'/wday/cxs/'+encodeURIComponent(config.tenant)+'/'+encodeURIComponent(config.site)+'/jobs';
 return {board:'Workday · <a target="_blank" rel="noopener noreferrer" href="'+esc(board)+'">Job board</a><details class="api-detail"><summary>JSON API (POST)</summary><code>'+esc(api)+'</code></details>',scope:config.search_term?'Search: '+esc(config.search_term):'All listed postings (configured)'};
}
function badge(label,kind){return '<span class="health-pill health-'+kind+'">'+esc(label)+'</span>'}
function statistic(label,value,detail){
 return '<div><div class="muted">'+esc(label)+'</div><strong>'+esc(value)+'</strong><p class="muted">'+esc(detail)+'</p></div>';
}
async function renderDashboard(){
 try {
  const [s,rows,sourceConfig]=await Promise.all([load('status.json'),load('history.csv'),load('sources.json').catch(()=>[])]);
  const h=healthSummary(s,rows),last=(s.run_time||'').slice(0,10);
  $('#run').textContent='Last recorded collection: '+fmtTime(s.run_time,'America/Chicago')+' ('+fmtTime(s.run_time,'UTC')+')';
  $('#cards').innerHTML=[['Successful UTC days',s.days_with_success||0],['Open postings',s.open||0],['New today',s.new_today||0],['Removed today',s.removed_today||0]].map(x=>'<div class="card"><div class="number">'+esc(x[1])+'</div>'+esc(x[0])+'</div>').join('');
  const time=utcNextSchedule();
  $('#update-health').innerHTML=
    '<div class="health-grid">'+
    statistic('Scheduled collection','Daily 10:19 UTC','4:19 AM CST / 5:19 AM CDT. GitHub may start late.')+
    statistic('Next scheduled run',fmtTime(time,'America/Chicago'),fmtTime(time,'UTC'))+
    statistic('Latest data saved',fmtTime(s.run_time,'America/Chicago'),fmtTime(s.run_time,'UTC'))+
    '<div><div class="muted">Collection health</div>'+badge(h.label,h.state)+'<p class="muted">'+h.working+'/'+h.configured+' configured sources returned JSON; '+h.broken+' failed. '+(h.offline?'Showing fallback browser cache.':'Snapshot age: '+Math.max(0,Math.round(h.ageHours))+'h.')+'</p></div>'+
    statistic('Employer coverage',h.working+' / '+h.list.length+' companies',h.unconfigured+' not configured; '+h.broken+' configured sources failed.')+
    statistic('Completeness review',String(h.review)+' sources', 'Exactly 40 or 0 listings; review pagination and source scope. These are not classified as request failures.')+
    '<div><div class="muted">History consistency</div>'+badge(h.consistent?'Counts agree':'Counts differ',h.consistent?'good':'bad')+'<p class="muted">'+h.rowsOpen+' open history rows vs '+esc(s.open)+' in status.json.</p></div>'+
    '</div><p class="muted">Operational health measures reported collection success and freshness. Coverage and source completeness are shown separately. The dashboard does not certify that all 25 boards were fully captured.</p>';
  const metadata=new Map(sourceConfig.map(x=>[x.name,x]));
  $('#sources').innerHTML=h.list.map(x=>{const state=sourceHealth(x),source=boardDetails(metadata.get(x.name));return '<tr><td>'+companyMark(x.name)+'</td><td>'+source.board+'</td><td>'+source.scope+'</td><td>'+badge(state.label,state.kind)+'</td><td>'+esc(x.count)+'</td><td>'+esc(state.detail)+'</td></tr>'}).join('')||'<tr><td colspan="6">No status report available</td></tr>';
  $('#new').innerHTML=rows.filter(r=>r.first_seen===last&&r.first_run==='false').map(r=>row(r)).join('')||'<tr><td colspan="5">No new postings detected. First-run positions are excluded.</td></tr>';
  $('#removed').innerHTML=rows.filter(r=>r.removed_date===last).map(r=>row(r)).join('')||'<tr><td colspan="5">No removed postings detected.</td></tr>';
 }catch(e){
  $('#run').textContent='Data unavailable: '+e.message;
  $('#update-health').textContent='Unable to verify data health.';
 }
}
renderDashboard();
