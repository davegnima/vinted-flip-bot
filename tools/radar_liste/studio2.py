# Uso: python3 -I studio2.py base | controllo <etichetta>
# Per ogni ricerca: annunci nuovi rispetto alla base (registrati dal tracker), prezzo mediano e i piu' economici.
import sys,re,html,json,os,statistics,urllib.request,datetime
D=os.path.dirname(os.path.abspath(__file__)); B='https://vinted-radar-production.up.railway.app'
get=lambda p: urllib.request.urlopen(B+p,timeout=40).read().decode()
t=get('/queries'); Q=[]
for m in re.finditer(r'action="/update_query/(\d+)"(.*?)</form>',t,flags=re.S):
    Q.append((m.group(1),html.unescape(re.search(r'name="query_name"[^>]*value="([^"]*)"',m.group(2)).group(1)).split(' :: ')[0]))
def items(qid):
    out=[]
    for row in re.findall(r'<tr.*?</tr>',get(f'/items?query={qid}&limit=100'),flags=re.S):
        u=re.search(r'/items/(\d+)',row)
        if not u: continue
        c=[re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',x))).strip() for x in re.findall(r'<td.*?</td>',row,flags=re.S)]
        try: p=float(c[2].split()[0])
        except: p=None
        out.append((u.group(1),c[1],p))
    return out
S={qid:items(qid) for qid,_ in Q}; fb=os.path.join(D,'base2.json')
if sys.argv[1]=='base':
    json.dump({q:[i[0] for i in v] for q,v in S.items()},open(fb,'w')); print('base:',sum(map(len,S.values())),'annunci in',len(S),'ricerche'); sys.exit()
base=json.load(open(fb)); righe=[]
for qid,n in Q:
    nuovi=[i for i in S[qid] if i[0] not in set(base.get(qid,[]))]
    righe.append((n,nuovi))
json.dump({'quando':datetime.datetime.now(datetime.UTC).isoformat(),'righe':[(n,[list(i) for i in v]) for n,v in righe]},open(os.path.join(D,f'studio2_{sys.argv[2]}.json'),'w'),ensure_ascii=False)
for gruppo,filtro in (('AVVISI (non studio)',lambda n: not n.startswith('STUDIO')),('STUDIO',lambda n: n.startswith('STUDIO'))):
    g=[(n,v) for n,v in righe if filtro(n)]; print(f"== {gruppo}: {sum(len(v) for _,v in g)} nuovi in {len(g)} ricerche")
    for n,v in sorted(g,key=lambda x:-len(x[1])):
        if not v: continue
        pr=[p for _,_,p in v if p]; med=statistics.median(pr) if pr else 0
        print(f"{len(v):4}  {n[:34]:34} mediana {med:6.0f} €   es: "+' ; '.join(f"{p:.0f}€ {tt[:28]}" for _,tt,p in sorted(v,key=lambda x:x[2] or 0)[:2]))
    print('   a zero:',sum(1 for _,v in g if not v))
