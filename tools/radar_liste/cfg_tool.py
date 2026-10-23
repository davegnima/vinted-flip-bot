import re,sys,html,hashlib,urllib.request,urllib.parse,ssl,os
B=os.environ.get('CFG_BASE','https://vinted-radar-production.up.railway.app')
def leggi():
    t=urllib.request.urlopen(B+'/config',timeout=30).read().decode()
    f={}
    for m in re.finditer(r'<input([^>]*)>',t):
        a=m.group(1); n=re.search(r'name="([^"]+)"',a)
        if not n: continue
        n=n.group(1); typ=(re.search(r'type="([^"]+)"',a) or [None,''])[1] if re.search(r'type="([^"]+)"',a) else ''
        if typ=='checkbox':
            f[n]=('on' if 'checked' in a else None)
        else:
            v=re.search(r'value="([^"]*)"',a); f[n]=html.unescape(v.group(1)) if v else ''
    for m in re.finditer(r'<textarea([^>]*)>(.*?)</textarea>',t,flags=re.S):
        n=re.search(r'name="([^"]+)"',m.group(1)).group(1); f[n]=html.unescape(m.group(2))
    return f
def impronta(f): return {k:(hashlib.sha256(str(v).encode()).hexdigest()[:8] if v is not None else None) for k,v in f.items()}
prima=leggi()
modo=sys.argv[1]
if modo=='mostra':
    for k,v in impronta(prima).items(): print(k,v, '' if any(s in k for s in ('token','chat','proxy')) else repr((prima[k] or '')[:80]))
    sys.exit()
nuovo=dict(prima)
for kv in sys.argv[2:]:
    k,v=kv.split('=',1); nuovo[k]=v
dati=[(k,v) for k,v in nuovo.items() if v is not None]
req=urllib.request.Request(B+'/update_config',data=urllib.parse.urlencode(dati).encode(),method='POST')
try: urllib.request.urlopen(req,timeout=30)
except Exception as e: print('post',type(e).__name__)
dopo=leggi()
a,b=impronta(prima),impronta(dopo)
for k in sorted(set(a)|set(b)):
    if a.get(k)!=b.get(k): print('CAMBIATO',k, '' if any(s in k for s in ('token','chat','proxy')) else (repr(prima.get(k))[:60],'->',repr(dopo.get(k))[:60]))
attesi=set(k for k,_ in [kv.split('=',1) for kv in sys.argv[2:]])
extra=[k for k in sorted(set(a)|set(b)) if a.get(k)!=b.get(k) and k not in attesi]
if extra:
    print('CAMBI NON VOLUTI, ripristino', extra)
    dati=[(k,v) for k,v in prima.items() if v is not None]
    urllib.request.urlopen(urllib.request.Request(B+'/update_config',data=urllib.parse.urlencode(dati).encode(),method='POST'),timeout=30)
    print('ripristinato', impronta(leggi())==impronta(prima))
print('fine')
