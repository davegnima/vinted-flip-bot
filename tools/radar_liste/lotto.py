# Carica un lotto di ricerche STUDIO "marca|modello|categoria > percorso" (lotto1.txt ...) sul radar.
# Il percorso si traduce negli id delle foglie dell'albero Vinted (dati/albero_categorie.json); percorso sconosciuto = solo testo.
# Le righe di moda (Donna/Uomo/Bambini vestiti, scarpe, sciarpe, cinture) NON si caricano: le copre il tracker moda.
# Senza lista modelli con prezzi veri le ricerche registrano soltanto, non avvisano. Uso: python3 lotto.py lotto1.txt [--carica]
import sys,os,re,html,json,urllib.request,urllib.parse
QUI=os.path.dirname(os.path.abspath(__file__)); B='https://vinted-radar-production.up.railway.app'
G=json.load(open(QUI+'/dati/albero_categorie.json'))
MODA=re.compile(r'^(Donna|Uomo|Bambini) > (Vestiti|Scarpe|Abbigliamento (bambino|bambina)|Accessori > (Sciarpe e scialli|Cinture))')
def foglie(n): return [n['id']] if not n['children'] else [i for c in n['children'].values() for i in foglie(c)]
def trova(p):
    n={'children':G}
    for x in [x.strip() for x in p.split('>')]:
        n=n['children'].get(x)
        if n is None: return None
    return n
def area(p): return {'Casa':'casa','Bellezza':'profumi','Uomo':'accessori','Donna':'accessori','Bambini':'bambini','Intrattenimento':'giochi'}[p.split('>')[0].strip()]
t=urllib.request.urlopen(B+'/queries',timeout=120).read().decode()
esist={html.unescape(x).split(' :: ')[0] for x in re.findall(r'name="query_name"[^>]*value="([^"]*)"',t)}
for l in open(os.path.join(QUI,sys.argv[1])):
    if not l.strip(): continue
    marca,modello,perc=[x.strip() for x in l.rstrip('\n').split('|')]
    if MODA.match(perc): print('MODA (tracker moda)',marca,modello); continue
    nome=f"STUDIO {area(perc)} {marca.lower()} {modello.lower()}"
    if nome in esist: print('GIA\'',nome); continue
    n=trova(perc); ids=foglie(n) if n else []
    u=f"https://www.vinted.it/catalog?search_text={urllib.parse.quote(marca+' '+modello)}&"+''.join(f'catalog[]={i}&' for i in ids)+"price_to=150&currency=EUR&order=newest_first"
    print(nome,ids if ids else 'solo testo')
    if '--carica' in sys.argv:
        urllib.request.urlopen(urllib.request.Request(B+'/add_query',data=urllib.parse.urlencode({'query':u,'query_name':nome}).encode(),method='POST'),timeout=60)
