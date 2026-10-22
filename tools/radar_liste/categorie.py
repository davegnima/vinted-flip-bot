# Ricerche larghe per categoria con lista modelli prezzati dalla tabella del bot (solo righe con prezzo).
import os as _os; _QUI=_os.path.dirname(_os.path.abspath(__file__)); _REPO=_os.path.abspath(_os.path.join(_QUI,'..','..'))
import sys,json,re,urllib.request,urllib.parse
sys.path.insert(0,_QUI); import envbot
from bot import radar_matrice as rm
M=rm.carica_matrice()
norm=lambda k:' '.join(rm._normalizza(k).split())
CAT={'G1 Console retro':('console_retro',[3026,3025,3027]),'G2 Lampade design':('illuminazione_design',[3836,3838,3839]),
     'G3 Audio':('audio',[3690,3680]),'G4 Borse vintage':('borse_vintage',[158,156]),'G5 Argento gioielli':('argento_gioielli',[5393]),
     'G6 Golf':('golf',[4470]),'G7 Collezionismo':('collezionismo',[97,5294])}
out=[]
for nome,(mod,cats) in CAT.items():
    voci={}
    for r in M:
        if r['radar']!=mod or not r.get('rivendita_veloce_eur'): continue
        bm=r['buy_max']; pz=f"{r['rivendita_veloce_eur']}/{0 if r.get('sotto_soglia') else ('?' if bm is None else bm)}"
        for k in r['chiavi']:
            k=norm(k)
            if k not in voci or r['rivendita_veloce_eur']<voci[k][0]: voci[k]=(r['rivendita_veloce_eur'],pz)
    lista=[f"{k}={v[1]}" for k,v in sorted(voci.items())]
    url='https://www.vinted.it/catalog?'+'&'.join(f'catalog[]={c}' for c in cats)+'&price_to=50&currency=EUR&order=newest_first'
    verdi=sum(1 for k,v in voci.items() if not v[1].endswith('/0') and not v[1].endswith('/?'))
    print(f"{nome:22} {len(lista):3} chiavi, {verdi} con buy max; {len(' | '.join(lista))} caratteri")
    out.append((nome,url,lista))
if '--carica' in sys.argv:
    B='https://vinted-radar-production.up.railway.app'
    for nome,url,lista in out:
        d={'query':url,'query_name':nome+' :: '+' | '.join(lista)}
        print(nome,urllib.request.urlopen(urllib.request.Request(B+'/add_query',data=urllib.parse.urlencode(d).encode(),method='POST'),timeout=40).status)
