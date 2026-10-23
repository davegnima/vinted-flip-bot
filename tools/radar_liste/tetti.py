# price_to di ogni ricerca con lista modelli = buy max piu' alto x 1,15 (arrotondato a 10), minimo 50.
import sys,re,html,math,urllib.request,urllib.parse
B='https://vinted-radar-production.up.railway.app'
t=urllib.request.urlopen(B+'/queries',timeout=40).read().decode()
for m in re.finditer(r'action="/update_query/(\d+)"(.*?)</form>',t,flags=re.S):
    qid=m.group(1); q=html.unescape(re.search(r'name="query"[^>]*value="([^"]*)"',m.group(2)).group(1))
    nome=html.unescape(re.search(r'name="query_name"[^>]*value="([^"]*)"',m.group(2)).group(1))
    if ' :: ' not in nome: continue
    bm=[int(b) for b in re.findall(r'=\d+/(\d+)\*?',nome) if int(b)>0]
    tetto=max(50,math.ceil(max(bm,default=0)*1.15/10)*10)
    nuovo=re.sub(r'price_to=\d+',f'price_to={tetto}',q)
    print(f"{qid:>4} {nome.split(' :: ')[0]:24} price_to {re.search(r'price_to=(\d+)',q).group(1)} -> {tetto}")
    if '--carica' in sys.argv and nuovo!=q:
        urllib.request.urlopen(urllib.request.Request(B+f'/update_query/{qid}',data=urllib.parse.urlencode({'query':nuovo,'query_name':nome}).encode(),method='POST'),timeout=40)
