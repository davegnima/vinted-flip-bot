# Radar v2 (23/10): sostituisce le ricerche del radar con ricerche SENZA lista modelli (nome "V2 ...").
# Ogni annuncio nuovo arriva al worker, che in modalita' ombra (RADAR_V2_OMBRA=1) calcola la rivendita dagli annunci simili.
# Uso: python3 v2_ricerche.py --salva   (salva nomi e URL delle ricerche attuali in docs/analisi/)
#      python3 v2_ricerche.py --carica  (toglie tutte le ricerche e carica le V2)
import sys,os,re,html,json,urllib.request,urllib.parse
QUI=os.path.dirname(os.path.abspath(__file__)); B='https://vinted-radar-production.up.railway.app'
POSATE=[1950,1951,1952,1970]; STOV=[1958,1959,1960,1961]; BIC=[2006,2007,2008,2009,2010,2011]; VASI=[1940]; LAMP=[3836,3837,3838,3839]
V2=[ # nome, testo, catalog, tetto
 ('V2 posate christofle','christofle',POSATE+[1961],50),('V2 posate sambonet','sambonet',POSATE+[1961],50),
 ('V2 posate in set','posate',[1950],30),('V2 ginori','ginori',STOV,50),('V2 baccarat','baccarat',BIC+VASI,50),
 ('V2 lalique','lalique',VASI,50),('V2 iittala','iittala',STOV+BIC+VASI,50),
 ('V2 le creuset','le creuset',[],50),('V2 staub','staub',[],50),('V2 smeg','smeg',[],50),('V2 kitchenaid','kitchenaid',[],50),
 ('V2 dyson airwrap','dyson airwrap',[],50),('V2 dyson supersonic','dyson supersonic',[],50),('V2 thermomix','thermomix',[],50),
 ('V2 airpods pro','airpods pro',[3678],50),('V2 sony wh 1000xm','sony wh 1000xm',[3678],50),('V2 switch oled','switch oled',[3025],50),
 ('V2 montblanc meisterstuck','montblanc meisterstuck',[],50),('V2 omega seamaster','omega seamaster',[97],50),
 ('V2 stokke tripp trapp','stokke tripp trapp',[],50),('V2 babyzen yoyo','babyzen yoyo',[],50),('V2 bugaboo','bugaboo',[],50),
]
def get(p): return urllib.request.urlopen(B+p,timeout=120).read().decode()
def post(p,d=None): return urllib.request.urlopen(urllib.request.Request(B+p,data=urllib.parse.urlencode(d or {}).encode(),method='POST'),timeout=120)
if '--salva' in sys.argv:
    out=[]
    for m in re.finditer(r'action="/update_query/(\d+)"(.*?)</form>',get('/queries'),flags=re.S):
        n=html.unescape(re.search(r'name="query_name"[^>]*value="([^"]*)"',m.group(2)).group(1)).split(' :: ')[0]
        u=html.unescape(re.search(r'name="query"[^>]*value="([^"]*)"',m.group(2)).group(1))
        out.append({'nome':n,'url':u})
    json.dump(out,open(QUI+'/../../docs/analisi/radar-ricerche-ferme-2026-10-23.json','w'),ensure_ascii=False,indent=0)
    print(len(out),'ricerche salvate')
if '--carica' in sys.argv:
    post('/remove_query/all'); print('tolte tutte')
    for nome,txt,cat,pt in V2:
        u=f"https://www.vinted.it/catalog?search_text={urllib.parse.quote(txt)}&"+''.join(f'catalog[]={i}&' for i in cat)+f"price_to={pt}&currency=EUR&order=newest_first"
        post('/add_query',{'query':u,'query_name':nome}); print('ok',nome)
