# Scarica gli annunci registrati dal radar per ricerca (con data) dalle 23:00 UTC del 18/10.
import os as _os; _QUI=_os.path.dirname(_os.path.abspath(__file__)); _REPO=_os.path.abspath(_os.path.join(_QUI,'..','..'))
import re,html,json,urllib.request,concurrent.futures as cf
B='https://vinted-radar-production.up.railway.app'; OUT=_QUI+'/d24.json'
get=lambda p: urllib.request.urlopen(B+p,timeout=120).read().decode()
t=get('/queries'); Q=[]
for m in re.finditer(r'action="/update_query/(\d+)"(.*?)</form>',t,flags=re.S):
    Q.append((m.group(1),html.unescape(re.search(r'name="query_name"[^>]*value="([^"]*)"',m.group(2)).group(1)).split(' :: ')[0]))
def items(qid):
    out=[]
    for row in re.findall(r'<tr.*?</tr>',get(f'/items?query={qid}&limit=1500'),flags=re.S):
        u=re.search(r'/items/(\d+)',row)
        if not u: continue
        c=[re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',x))).strip() for x in re.findall(r'<td.*?</td>',row,flags=re.S)]
        try: p=float(c[2].split()[0])
        except: p=None
        out.append((u.group(1),c[1],p,c[4]))
    return out
with cf.ThreadPoolExecutor(4) as ex: R=dict(zip([n for _,n in Q],ex.map(items,[q for q,_ in Q])))
json.dump(R,open(OUT,'w'),ensure_ascii=False)
print(len(R),sum(map(len,R.values())))
