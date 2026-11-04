import csv,json,subprocess,re
from datetime import datetime,timezone
from pathlib import Path
root=Path(__file__).parent;day=datetime.now(timezone.utc).date().isoformat()
rows=list(csv.DictReader((root/'data/history.csv').open(encoding='utf8',newline='')))
status=json.loads((root/'data/status.json').read_text())
new=[r for r in rows if r['first_seen']==day and r['first_run']=='false']
gone=[r for r in rows if r['removed_date']==day]
def display(items):
    return '\n'.join('- ['+r['employer']+': '+r['title']+']('+r['url']+')' if r['url'] else '- '+r['employer']+': '+r['title'] for r in items) or '- None'
body='## New ('+str(len(new))+')\n'+display(new)+'\n\n## Removed ('+str(len(gone))+')\n'+display(gone)+'\n\n## Sources\n'+'\n'.join('- '+s['name']+': '+('OK' if s['ok'] else 'Failed')+' ('+str(s['count'])+')' for s in status['sources'])
def gh(*args):return subprocess.run(['gh',*args],capture_output=True,text=True,check=True).stdout.strip()
issues=json.loads(gh('issue','list','--state','all','--limit','100','--json','number,title,state'))
existing=next((i for i in issues if i['title']==day),None)
if existing:
    gh('issue','edit',str(existing['number']),'--body',body)
    if existing['state']=='CLOSED':gh('issue','reopen',str(existing['number']))
else:gh('issue','create','--title',day,'--body',body)
for i in issues:
    if i['title']!=day and i['state']=='OPEN' and re.fullmatch(r'\d{4}-\d{2}-\d{2}',i['title']):gh('issue','close',str(i['number']))
