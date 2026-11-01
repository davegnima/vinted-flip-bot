# Radar v2 (23/10): sostituisce le ricerche del radar con ricerche SENZA lista modelli (nome "V2 ...").
# Ogni annuncio nuovo arriva al worker, che in modalita' ombra (RADAR_V2_OMBRA=1) calcola la rivendita dagli annunci simili.
# Uso: python3 v2_ricerche.py --salva   (salva nomi e URL delle ricerche attuali in docs/analisi/)
#      python3 v2_ricerche.py --carica  (toglie tutte le ricerche e carica le V2)
#      python3 v2_ricerche.py --aggiungi (aggiunge solo le OSS in osservazione, senza toccare le altre)
#      python3 v2_ricerche.py --console  (aggiunge le 9 ricerche console e giochi dell'ondata 1, 31/10)
#      python3 v2_ricerche.py --onda3    (aggiunge il resto della lista V2 non ancora sul tracker, senza categorie a rischio; 31/10)
#      python3 v2_ricerche.py --onda4    (aggiunge le ricerche di categorie nuove: LEGO, pedali, retro games, strumenti; 01/11)
#      python3 v2_ricerche.py --onda2    (aggiunge le 14 ricerche per brand di utensili, hi-fi, foto, casa, bimbi: raccolta dati larga, 31/10)
import sys,os,re,html,json,urllib.request,urllib.parse
QUI=os.path.dirname(os.path.abspath(__file__)); B='https://vinted-radar-production.up.railway.app'
POSATE=[1950,1951,1952,1970]; STOV=[1958,1959,1960,1961]; BIC=[2006,2007,2008,2009,2010,2011]; VASI=[1940]; LAMP=[3836,3837,3838,3839]
B_=json.load(open(QUI+'/dati/brand_ids.json'))['marchi']
V2=[ # nome, testo, brand (nome o None), catalog, tetto
 ('V2 posate christofle','','christofle',POSATE+[1961],50),('V2 posate sambonet','','sambonet',POSATE+[1961],50),
 ('V2 ginori','','richard ginori',STOV,50),('V2 baccarat','','baccarat',BIC+VASI,50),
 ('V2 lalique','','lalique',VASI,50),('V2 iittala','','iittala',STOV+BIC+VASI,50),
 ('V2 le creuset','','le creuset',[3507,3508,3510],50),('V2 staub','staub',None,[3507,3508,3510],50),('V2 smeg','','smeg',[],50),('V2 kitchenaid','','kitchenaid',[],50),
 ('V2 dyson','','dyson',[],50),('V2 thermomix','thermomix',None,[],50),
 ('V2 airpods pro','airpods pro',None,[3678],50),('V2 sony cuffie','','sony',[3678],50),('V2 switch oled','switch oled',None,[3025],50),
 ('V2 montblanc penne','','montblanc',[5456],50),('V2 omega uomo','','omega',[97],50),('V2 omega donna','','omega',[22],50),
 ('V2 stokke seggioloni','','stokke',[3450],50),('V2 babyzen','','babyzen',[1612],50),('V2 bugaboo','','bugaboo',[1612],50),
 ('V2 artemide','','artemide',LAMP,50),('V2 flos','','flos',LAMP,50),('V2 kartell','','kartell',LAMP,50),('V2 rosenthal','','rosenthal',STOV,50),
 ('V2 venini','','venini',[],50),('V2 zwilling','','zwilling',[3507,3508,3510],50),('V2 alessi','','alessi',STOV+[3862],50),
 ('V2 sonos','','sonos',[3695,3682,3697,3678],50),('V2 bang olufsen','','bang olufsen',[3694,3695,3678,3701],50),
 ('V2 technics','','technics',[3701],50),('V2 marantz','','marantz',[3699,3694],50),('V2 leica','','leica',[3075,3076],50),
 ('V2 fujifilm','','fujifilm',[3075,3076],50),('V2 dji','','dji',[3723,3074],50),('V2 gopro','','gopro',[3074],50),
 ('V2 garmin','','garmin',[3035,3004],50),('V2 bose','','bose',[3678,3695],50),('V2 sennheiser','','sennheiser',[3678],50),
 ('V2 apple airpods','','apple',[3678],50),('V2 makita','','makita',[3875],50),('V2 festool','','festool',[],50),
 ('V2 milwaukee','','milwaukee',[3875],50),('V2 dewalt','','dewalt',[3875],50),('V2 nuna','','nuna',[1612],50),('V2 joolz','','joolz',[1612],50),
 ('V2 ghd','','ghd',[3766],50),('V2 longines','','longines',[97,22],50),('V2 tudor','','tudor',[97,22],50),('V2 games workshop','','games workshop',[4883],50),
]
OSS=[ # osservazione fuori moda (24/10): categorie larghe, nessun brand, tetto 50; il radar valuta e registra, niente Telegram
 ('V2 OSS fumetti manga','',None,[5425],50),('V2 OSS libri universitari','universitari',None,[5426],50),('V2 OSS giochi da tavolo','',None,[4881],50),
]
CONSOLE=[ # 31/10, ondata 1 (console e giochi): ricerche con testo = un prodotto preciso, cosi' il worker calcola il riferimento di prezzo UNA volta per ricerca.
 # nome, testo, brand, catalog, tetto (tetto per categoria: console fino a 150 EUR, retro/giochi piu' bassi)
 ('V2 ps5','ps5',None,[3025],150),('V2 switch oled','switch oled',None,[3025],120),('V2 switch','nintendo switch',None,[3025],90),
 ('V2 steam deck','steam deck',None,[3025],150),('V2 xbox series x','xbox series x',None,[3025],150),('V2 ps4 pro','ps4 pro',None,[3025],60),
 ('V2 game boy','game boy',None,[3025],50),('V2 3ds','3ds',None,[3025],60),('V2 giochi switch ps5','switch ps5',None,[3026],25),
]
ONDA2=[ # 31/10, raccolta dati larga (richiesta dell'utente): brand ovvi di categorie diverse, tetti di partenza (stime da correggere con i dati)
 ('V2 makita','','makita',[3875],100),('V2 milwaukee','','milwaukee',[3875],100),('V2 dewalt','','dewalt',[3875],100),
 ('V2 sonos','','sonos',[3695,3682,3697,3678],100),('V2 bang olufsen','','bang olufsen',[3694,3695,3678,3701],150),
 ('V2 technics','','technics',[3701],150),('V2 marantz','','marantz',[3699,3694],150),('V2 leica','','leica',[3075,3076],150),
 ('V2 fujifilm','','fujifilm',[3075,3076],100),('V2 dji','','dji',[3723,3074],100),('V2 dyson','','dyson',[3543],100),
 ('V2 kitchenaid','','kitchenaid',[],80),('V2 stokke seggioloni','','stokke',[3450],60),('V2 bugaboo','','bugaboo',[1612],60),
]
ONDA4=[ # 01/11, categorie nuove (richiesta dell'utente: "altri affari da altre categorie"). Ricerche di testo su prodotti precisi, senza id categoria
 # inventati (solo 3025/3026 gia' visti nei log); tetto 50 EUR (regola 10). Il bot scarta i falsi con Jev + Gemini; da misurare con anomalie.py e RIEPILOGO BANDA.
 ('V2 lego star wars','lego star wars',None,[],50),('V2 lego technic','lego technic',None,[],50),('V2 lego ideas icons','lego ideas icons',None,[],50),
 ('V2 lego sigillato','lego sigillato',None,[],50),
 ('V2 pedale boss','boss pedale chitarra',None,[],50),('V2 pedale electro harmonix','electro harmonix',None,[],50),('V2 pedale mxr','mxr pedale',None,[],50),
 ('V2 gamecube','gamecube',None,[3025,3026],50),('V2 nintendo 64','nintendo 64',None,[3025,3026],50),('V2 super nintendo','super nintendo snes',None,[3025,3026],50),
 ('V2 game boy advance','game boy advance',None,[3025,3026],50),
]
ONDA5=[ # 01/11 (b), 10 filoni nuovi (strumenti musicali, retrogaming boutique, rete/casa smart, epilatori). PROVVISORIE: ricerche di testo strette SENZA catalog[] (id non noti, non inventati);
 # dopo qualche ora si leggono i catalog[] veri dai log del worker e si aggiornano con POST /update_query/<id> (regola: nessuna ricerca per brand senza categoria). Tetti dalla proposta dell'utente.
 ('V2 teenage engineering op-1','teenage engineering op-1',None,[],150),('V2 roland sp-404','roland sp-404',None,[],150),('V2 korg volca','korg volca',None,[],50),
 ('V2 focusrite scarlett 2i2','focusrite scarlett 2i2',None,[],40),('V2 analogue pocket','analogue pocket',None,[],150),('V2 playdate','playdate console',None,[],100),
 ('V2 netgear orbi','netgear orbi',None,[],80),('V2 tado termostato','tado termostato',None,[],60),('V2 philips lumea','philips lumea',None,[],100),
 ('V2 braun silk expert pro 5','braun silk expert pro 5',None,[],100),
]
ONDA6=[ # 01/11 (c), 39 ricerche dall'elenco 'High-Liquid' dell'utente. PROVVISORIE senza catalog[] (id non noti, non inventati); da correggere con i catalog[] letti nei log.
 # Escluse perche' gia' presenti o potate con dati: lego technic / star wars (solo rossi), kitchenaid (accessori), le creuset, staub, stokke, bugaboo (gia' sul tracker), op-1 / sp-404 / volca / scarlett (ONDA5).
 ('V2 ryzen 7 5800x3d','ryzen 7 5800x3d',None,[],120), ('V2 ryzen 7 7800x3d','ryzen 7 7800x3d',None,[],150), ('V2 rtx 3060','rtx 3060',None,[],120), ('V2 rtx 3070','rtx 3070',None,[],150), ('V2 samsung 990 pro 1tb','samsung 990 pro 1tb',None,[],60), ('V2 logitech g pro x superlight','logitech g pro x superlight',None,[],50), ('V2 wooting 60he','wooting 60he',None,[],90), ('V2 elgato stream deck','elgato stream deck',None,[],60), ('V2 meta quest 3','meta quest 3',None,[],150), ('V2 dualsense edge','dualsense edge',None,[],90), ('V2 dji pocket 3','dji pocket 3',None,[],150), ('V2 dji mini 3 pro','dji mini 3 pro',None,[],150), ('V2 insta360 x3','insta360 x3',None,[],150), ('V2 gopro hero 12','gopro hero 12',None,[],150), ('V2 sony zv-1','sony zv-1',None,[],150), ('V2 sigma 16mm sony','sigma 16mm sony',None,[],100), ('V2 rode wireless go ii','rode wireless go ii',None,[],80), ('V2 dji mic 2','dji mic 2',None,[],120), ('V2 zoom h6','zoom h6',None,[],70), ('V2 dji ronin rs3','dji ronin rs3',None,[],150), ('V2 babyzen yoyo','babyzen yoyo',None,[],150), ('V2 cybex cloud z','cybex cloud z',None,[],90), ('V2 berkel affettatrice','berkel affettatrice',None,[],150), ('V2 warhammer 40k','warhammer 40k',None,[],60), ('V2 heroquest','heroquest',None,[],50), ('V2 bullpadel vertex','bullpadel vertex',None,[],70), ('V2 babolat pure drive','babolat pure drive',None,[],50), ('V2 head speed pro','head speed pro',None,[],70), ('V2 garmin fenix 7','garmin fenix 7',None,[],150), ('V2 wahoo elemnt','wahoo elemnt',None,[],70), ('V2 garmin edge','garmin edge',None,[],80), ('V2 favero assioma','favero assioma',None,[],150), ('V2 comandante c40','comandante c40',None,[],80), ('V2 fellow stagg','fellow stagg',None,[],50), ('V2 eureka mignon','eureka mignon',None,[],100), ('V2 chord mojo','chord mojo',None,[],120), ('V2 fiio btr','fiio btr',None,[],40), ('V2 fanatec csl','fanatec csl',None,[],100), ('V2 thrustmaster warthog','thrustmaster warthog',None,[],120),
]
RISCHIO=('V2 alessi','V2 iittala','V2 rosenthal','V2 zwilling','V2 gopro','V2 dji', # 01/11 (b) potate: margine_basso 90% (prezzi 15-28 EUR) o 0 vendite veloci su 38 tracciate (URL in docs/analisi/radar-ricerche-potate-2026-11-01-b.json)
         'V2 games workshop','V2 smeg','V2 ginori', # 01/11 potate: 0 gialli/verdi su 24 h, 91-100% margine_basso (URL salvate in docs/analisi/radar-ricerche-potate-2026-11-01.json)
         'V2 airpods pro','V2 apple airpods','V2 omega uomo','V2 omega donna','V2 longines','V2 tudor','V2 montblanc penne', # repliche frequenti: fuori (piano 31/10)
         'V2 lalique','V2 babyzen','V2 flos','V2 venini','V2 nuna','V2 lego star wars','V2 lego technic','V2 game boy', # 01/11 (c) tolte dal tracker: 0 annunci in 24 h (lalique, babyzen, flos, venini, nuna) o solo rossi (lego star wars 310, lego technic 106, game boy 16)
         'V2 thermomix','V2 kitchenaid') # 31/10 13:30: senza catalog[] solo rumore (thermomix limite=0, kitchenaid accessori); rimesse solo con l'id categoria visto nei log
def _nomi_sul_tracker():
    return {html.unescape(re.search(r'name="query_name"[^>]*value="([^"]*)"',m.group(2)).group(1)).split(' :: ')[0]
            for m in re.finditer(r'action="/update_query/(\d+)"(.*?)</form>',get('/queries'),flags=re.S)}
def get(p): return urllib.request.urlopen(B+p,timeout=120).read().decode()
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**k): return None
_APRI=urllib.request.build_opener(_NoRedirect)
def post(p,d=None):
    try: return _APRI.open(urllib.request.Request(B+p,data=urllib.parse.urlencode(d or {}).encode(),method='POST'),timeout=120)
    except urllib.error.HTTPError as e:
        if e.code not in (302,303): raise
        return e
if '--salva' in sys.argv:
    out=[]
    for m in re.finditer(r'action="/update_query/(\d+)"(.*?)</form>',get('/queries'),flags=re.S):
        n=html.unescape(re.search(r'name="query_name"[^>]*value="([^"]*)"',m.group(2)).group(1)).split(' :: ')[0]
        u=html.unescape(re.search(r'name="query"[^>]*value="([^"]*)"',m.group(2)).group(1))
        out.append({'nome':n,'url':u})
    json.dump(out,open(QUI+'/../../docs/analisi/radar-ricerche-ferme-2026-10-23.json','w'),ensure_ascii=False,indent=0)
    print(len(out),'ricerche salvate')
if '--aggiungi' in sys.argv:
    for nome,txt,br,cat,pt in OSS:
        u='https://www.vinted.it/catalog?'+(f'search_text={urllib.parse.quote(txt)}&' if txt else '')+(f'brand_ids[]={B_[br]}&' if br else '')+''.join(f'catalog[]={i}&' for i in cat)+f"price_to={pt}&currency=EUR&order=newest_first"
        post('/add_query',{'query':u,'query_name':nome}); print('ok',nome)
if '--console' in sys.argv:
    for nome,txt,br,cat,pt in CONSOLE:
        u='https://www.vinted.it/catalog?'+(f'search_text={urllib.parse.quote(txt)}&' if txt else '')+(f'brand_ids[]={B_[br]}&' if br else '')+''.join(f'catalog[]={i}&' for i in cat)+f"price_to={pt}&currency=EUR&order=newest_first"
        post('/add_query',{'query':u,'query_name':nome}); print('ok',nome)
if '--onda2' in sys.argv:
    for nome,txt,br,cat,pt in ONDA2:
        u='https://www.vinted.it/catalog?'+(f'search_text={urllib.parse.quote(txt)}&' if txt else '')+(f'brand_ids[]={B_[br]}&' if br else '')+''.join(f'catalog[]={i}&' for i in cat)+f"price_to={pt}&currency=EUR&order=newest_first"
        post('/add_query',{'query':u,'query_name':nome}); print('ok',nome)
if '--onda4' in sys.argv:
    gia=_nomi_sul_tracker()
    for nome,txt,br,cat,pt in ONDA4:
        if nome in gia: continue
        u='https://www.vinted.it/catalog?'+(f'search_text={urllib.parse.quote(txt)}&' if txt else '')+(f'brand_ids[]={B_[br]}&' if br else '')+''.join(f'catalog[]={i}&' for i in cat)+f"price_to={pt}&currency=EUR&order=newest_first"
        post('/add_query',{'query':u,'query_name':nome}); print('ok',nome)
if '--onda5' in sys.argv:
    gia=_nomi_sul_tracker()
    for nome,txt,br,cat,pt in ONDA5:
        if nome in gia: continue
        u='https://www.vinted.it/catalog?'+(f'search_text={urllib.parse.quote(txt)}&' if txt else '')+(f'brand_ids[]={B_[br]}&' if br else '')+''.join(f'catalog[]={i}&' for i in cat)+f"price_to={pt}&currency=EUR&order=newest_first"
        post('/add_query',{'query':u,'query_name':nome}); print('ok',nome)
if '--onda6' in sys.argv:
    gia=_nomi_sul_tracker()
    for nome,txt,br,cat,pt in ONDA6:
        if nome in gia: continue
        u='https://www.vinted.it/catalog?'+f'search_text={urllib.parse.quote(txt)}&'+''.join(f'catalog[]={i}&' for i in cat)+f"price_to={pt}&currency=EUR&order=newest_first"
        post('/add_query',{'query':u,'query_name':nome}); print('ok',nome)
if '--onda3' in sys.argv:
    gia=_nomi_sul_tracker()
    for nome,txt,br,cat,pt in V2:
        if nome in gia or nome in RISCHIO: continue
        u='https://www.vinted.it/catalog?'+(f'search_text={urllib.parse.quote(txt)}&' if txt else '')+(f'brand_ids[]={B_[br]}&' if br else '')+''.join(f'catalog[]={i}&' for i in cat)+f"price_to={pt}&currency=EUR&order=newest_first"
        post('/add_query',{'query':u,'query_name':nome}); print('ok',nome)
if '--carica' in sys.argv:
    post('/remove_query/all'); print('tolte tutte')
    for nome,txt,br,cat,pt in V2:
        u='https://www.vinted.it/catalog?'+(f'search_text={urllib.parse.quote(txt)}&' if txt else '')+(f'brand_ids[]={B_[br]}&' if br else '')+''.join(f'catalog[]={i}&' for i in cat)+f"price_to={pt}&currency=EUR&order=newest_first"
        post('/add_query',{'query':u,'query_name':nome}); print('ok',nome)
