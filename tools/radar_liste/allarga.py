# Allarga il radar: ricerche con prezzo (Lego per tema, arredo per brand) + ricerche STUDIO (registrano, non avvisano).
import os as _os; _QUI=_os.path.dirname(_os.path.abspath(__file__)); _REPO=_os.path.abspath(_os.path.join(_QUI,'..','..'))
import sys,json,math,re,urllib.request,urllib.parse
sys.path.insert(0,_QUI); import envbot
from bot import radar_matrice as rm
M=rm.carica_matrice(); norm=lambda k:' '.join(rm._normalizza(k).split())
def lista(mod):
    v={}
    for r in M:
        if r['radar']!=mod or not r.get('rivendita_veloce_eur'): continue
        bm=r['buy_max']; pz=f"{r['rivendita_veloce_eur']}/{0 if r.get('sotto_soglia') else ('?' if bm is None else bm)}"
        for k in r['chiavi']:
            k=norm(k)
            if k not in v or r['rivendita_veloce_eur']<v[k][0]: v[k]=(r['rivendita_veloce_eur'],pz)
    return [f"{k}={p}" for k,(_,p) in sorted(v.items())]
def tetto(l):
    bm=[int(b) for b in re.findall(r'=\d+/(\d+)',' | '.join(l)) if int(b)>0]; return max(50,math.ceil(max(bm,default=0)*1.15/10)*10)
U='https://www.vinted.it/catalog?'
Q=[]
LEGO=lista('lego'); LC='&catalog[]=1767&brand_ids[]=89162'
for tema in ('star wars','technic','ucs','modular','ideas','creator expert','harry potter','ninjago','marvel','city'):
    Q.append((f"H Lego {tema}",f"{U}search_text={urllib.parse.quote_plus(tema)}{LC}&price_to={tetto(LEGO)}&currency=EUR&order=newest_first",LEGO))
ARR=lista('arredo_design')
for b in ('cassina','kartell','vitra','zanotta'):
    Q.append((f"H Arredo {b}",f"{U}search_text={b}&price_to={tetto(ARR)}&currency=EUR&order=newest_first",ARR))
STUDIO={'casa':['alessi','smeg','kitchenaid','le creuset','staub','dyson','thermomix','iittala','rosenthal','villeroy boch','richard ginori','venini','murano','royal copenhagen','arabia finland','bitossi','tom dixon','hay','muuto','herman miller','eames','kartell','flos','artemide'],
 'elettronica':['bose','sonos','marshall','airpods max','airpods pro','ipad','macbook','apple watch','kindle','switch oled','steam deck','ps vita','gopro','dji','garmin','sony wh 1000xm','bang olufsen','polaroid','instax','leica'],
 'sport':['shimano','campagnolo','salomon','la sportiva','black diamond','petzl','burton','oakley','titleist','scotty cameron','babolat'],
 'giochi':['warhammer','magic the gathering','pokemon carte','yu gi oh','hot wheels redline','lego','game boy','nintendo 64'],
 'musica':['vinile','fender','gibson','roland','korg','moog','boss pedale','technics','marantz','revox'],
 'occhiali':['persol','ray ban','oliver peoples','cazal','matsuda','moscot'],
 'bijoux':['chanel orecchini','dior orecchini','ysl orecchini','lacroix','swarovski','pandora']}
for cat,ks in STUDIO.items():
    for k in ks: Q.append((f"STUDIO {cat} {k}",f"{U}search_text={urllib.parse.quote_plus(k)}&price_to=150&currency=EUR&order=newest_first",None))
print(len(Q),'ricerche;',sum(1 for q in Q if q[2]),'con prezzo; tetto lego',tetto(LEGO),'arredo',tetto(ARR),'; caratteri lista lego',len(' | '.join(LEGO)))
if '--carica' in sys.argv:
    B='https://vinted-radar-production.up.railway.app'
    for n,u,l in Q:
        d={'query':u,'query_name':n+(' :: '+' | '.join(l) if l else '')}
        urllib.request.urlopen(urllib.request.Request(B+'/add_query',data=urllib.parse.urlencode(d).encode(),method='POST'),timeout=40)
    t=urllib.request.urlopen(B+'/queries',timeout=40).read().decode(); print('ricerche ora:',len(set(re.findall(r'update_query/(\d+)',t))))
