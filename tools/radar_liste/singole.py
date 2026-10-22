# Liste con prezzo per le ricerche singole del radar (tabella del bot dove c'e', altrimenti stime mie marcate '*').
import os as _os; _QUI=_os.path.dirname(_os.path.abspath(__file__)); _REPO=_os.path.abspath(_os.path.join(_QUI,'..','..'))
import sys,json,re,html,urllib.request,urllib.parse
sys.path.insert(0,_QUI); import envbot
from bot import radar_matrice as rm
M=rm.carica_matrice(); byid={r['id']:r for r in M}
def tab(prefix):
    r=next(r for r in M if r['id'].startswith(prefix)); bm=r['buy_max']
    return f"{r['rivendita_veloce_eur']}/{'?' if bm is None else bm}"
def stima(rv,sped=6): return f"{rv}/{rm.buy_max(rv,sped,1,2) if rv>=100 else 0}*"
L={
 'C5 Game Boy Micro':{'game boy micro':tab('nintendo_game_boy_micro'),'gameboy micro':tab('nintendo_game_boy_micro')},
 'S27 PSP Go':{'psp go':stima(110)},
 'S28 New 3DS XL':{'new 3ds xl':tab('nintendo_new_nintendo_3ds_xl'),'new nintendo 3ds xl':tab('nintendo_new_nintendo_3ds_xl')},
 'S31 Walkman WM-D6C':{'wm d6c':tab('sony_walkman_professional_wm_d6c'),'walkman d6c':tab('sony_walkman_professional_wm_d6c')},
 'S32 Walkman DD':{'walkman dd':tab('sony_walkman_dd'),'wm dd':tab('sony_walkman_dd')},
 'S33 Sennheiser HD 600':{'hd 600':tab('sennheiser_hd_600'),'hd600':tab('sennheiser_hd_600')},
 'S34 Sennheiser HD 650':{'hd 650':tab('sennheiser_hd_600'),'hd650':tab('sennheiser_hd_600')},
 'S36 Technics 1200':{'sl 1200':stima(400,15),'sl1200':stima(400,15),'technics 1200':stima(400,15)},
 'S41 Louis Poulsen':{'panthella':tab('louis_poulsen_panthella'),'ph 5':stima(400,10),'ph5':stima(400,10),'ph 3 2':stima(500,10)},
 'S45 Seiko 6139':{'6139':tab('seiko_6139'),'pogue':tab('seiko_6139')},
 'S46 Montblanc 146 149':{'montblanc 146':tab('montblanc_meisterstuck_146'),'meisterstuck 146':tab('montblanc_meisterstuck_146'),'montblanc 149':tab('montblanc_meisterstuck_149'),'meisterstuck 149':tab('montblanc_meisterstuck_149')},
 'S50 Carhartt Detroit':{'carhartt detroit':stima(110),'detroit jacket':stima(110)},
 'S47a Arcteryx Beta':{'arc teryx beta':stima(220)},
 'S47b Arcteryx Alpha':{'arc teryx alpha':stima(280)},
 'S47c Arcteryx Atom':{'arc teryx atom':stima(110)},
 'S49 TNF Nuptse 1996':{'nuptse 1996':stima(130),'1996 retro nuptse':stima(130)},
}
TOGLI=('S37 iPod Classic','S47d Arcteryx Kyanite')
for n,v in L.items(): print(f"{n:24}", ' | '.join(f"{k}={p}" for k,p in v.items()))
if '--carica' in sys.argv:
    B='https://vinted-radar-production.up.railway.app'
    t=urllib.request.urlopen(B+'/queries',timeout=40).read().decode()
    for m in re.finditer(r'action="/update_query/(\d+)"(.*?)</form>',t,flags=re.S):
        qid=m.group(1); q=html.unescape(re.search(r'name="query"[^>]*value="([^"]*)"',m.group(2)).group(1))
        nome=html.unescape(re.search(r'name="query_name"[^>]*value="([^"]*)"',m.group(2)).group(1)).split(' :: ')[0]
        if nome in TOGLI:
            print('tolgo',nome,urllib.request.urlopen(urllib.request.Request(B+f'/remove_query/{qid}',method='POST'),timeout=40).status)
        elif nome in L:
            d={'query':q,'query_name':nome+' :: '+' | '.join(f"{k}={p}" for k,p in L[nome].items())}
            print(qid,nome,urllib.request.urlopen(urllib.request.Request(B+f'/update_query/{qid}',data=urllib.parse.urlencode(d).encode(),method='POST'),timeout=40).status)
