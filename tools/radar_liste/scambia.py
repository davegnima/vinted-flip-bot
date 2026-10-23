# Toglie le ricerche fotocamere singole (C1-C4, S06-S25) e aggiunge le larghe F1-F3.
import json,re,urllib.request,urllib.parse,html
B='https://vinted-radar-production.up.railway.app'
def get(p): return urllib.request.urlopen(B+p,timeout=40).read().decode()
def post(p,d=None): return urllib.request.urlopen(urllib.request.Request(B+p,data=urllib.parse.urlencode(d or {}).encode(),method='POST'),timeout=40).status
q=get('/queries')
nomi={int(m.group(1)):html.unescape(m.group(2)) for m in re.finditer(r'update_query/(\d+)".*?name="query_name"[^>]*value="([^"]*)"',q,flags=re.S)}
via=[i for i,n in nomi.items() if re.match(r'(C[1-4]|S(0[6-9]|1\d|2[0-5]))[a-z]? ',n)]
print('tolgo',sorted(nomi[i] for i in via))
for i in via: post(f'/remove_query/{i}')
for n,u,m in json.load(open('ricerche.json')):
    print(n,post('/add_query',{'query':u,'query_name':n+' :: '+' | '.join(m)}))
q=get('/queries'); print('ricerche ora:',len(set(re.findall(r'update_query/(\d+)',q))))
