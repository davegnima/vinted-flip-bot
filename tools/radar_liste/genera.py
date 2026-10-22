# Genera i nomi di F1/F2 con prezzi dalla matrice e li carica sul radar (--carica).
import os as _os; _QUI=_os.path.dirname(_os.path.abspath(__file__)); _REPO=_os.path.abspath(_os.path.join(_QUI,'..','..'))
import sys,json,re,urllib.request,urllib.parse
sys.path.insert(0,_QUI); import envbot
from bot import radar_matrice as rm
D=_QUI+'/'
p=[r for r in rm.prepara(json.load(open(_REPO+'/data/radar_matrice.json'))) if r['radar']=='fotografia']
LENTI=('Summicron','Summilux','Elmarit','Elmar','Summaron','FD','Nikkor','Nokton','Color','Ultron','Super','SMC','MC','Rokkor','Pancolar','Sonnar','Tessar','XF','EF','FE','AF','Planar','Helios','Sigma','105','80')
lente=lambda r: r['brand'].startswith('Carl Zeiss') or r['modello'].split()[0].split('-')[0] in LENTI or 'obiettivo' in r.get('note','').lower()[:0]
P=_QUI+'/dati/'
_ch=lambda f:{' '.join(re.sub(r'[^\w]+',' ',c.lower()).split()) for m in json.load(open(P+f)) for c in m['chiavi']}
CH_D,CH_E=_ch('gruppo_D.json'),_ch('gruppo_E.json')
digitale=lambda r: bool(set(r['chiavi'])&CH_D)
_lente_vecchia=lente
lente=lambda r: bool(set(r['chiavi'])&CH_E) or (_lente_vecchia(r) and not digitale(r))
# Stime mie (rivendita veloce in EUR) per i modelli con meno di 3 venduti trovati: marcate '*' nel messaggio.
STIME={'horizon_kompakt':120,'ricoh_gr10':300,'ricoh_gr21':800,'natura_black':450,'natura_classica':250,'tvs_ii':350,
 'fujifilm_x30':300,'fujifilm_xf10':400,'rx1':700,'g5_x':350,'gr_digital_iii':200,'ricoh_gr_aps':350,'d_lux_7':650,
 'leica_x1':400,'rokkor_pg_58':400,'pancolar':70,'tessar_50':30,'fe_50':110}
def stima(r):
    for k,v in STIME.items():
        if k in r['id']: return v
def prezzo(r):
    rv=r.get('rivendita_veloce_eur')
    if rv is None:
        rv=stima(r)
        if rv is None: return None
        bm=rm.buy_max(rv,r.get('spedizione_eur'),r.get('rischio_falsi'),r.get('rischio_guasti'))
        return f"{rv}/{bm if rv>=100 else 0}*"
    if r.get('sotto_soglia') or r.get('buy_max')==0: return f"{rv}/0"
    return f"{rv}/{'?' if r['buy_max'] is None else r['buy_max']}"
ric=json.load(open(D+'ricerche.json'))
norm=lambda k:' '.join(rm._normalizza(k).split())
gruppi=[lambda r: not lente(r) and not digitale(r), lente, digitale]
for idx,sel in enumerate(gruppi):
    voci={}
    for r in p:
        if not sel(r): continue
        pz=prezzo(r)
        for k in r['chiavi']:
            k=norm(k); rv=r.get('rivendita_veloce_eur') or 10**6
            if k not in voci or rv<voci[k][0]: voci[k]=(rv,pz)
    # Trappole economiche (stime mie): modelli che le chiavi larghe prenderebbero col prezzo di un modello caro.
    for k,v in {0:{'nikon fm10':'60/0*','om 10':'40/0*','om10':'40/0*','om 20':'50/0*','om 2000':'50/0*','canon eos':'40/0*','minolta dynax':'30/0*'},
                1:{}, 2:{}}[idx].items():
        voci.setdefault(k,(0,v))
    gen=[]
    for k in (norm(k) for k in ric[idx][2]):
        if k in voci: continue
        pz={v[1] for kk,v in voci.items() if set(k.split())<=set(kk.split())}
        if len(pz)==1: voci[k]=(0,pz.pop())
        else: gen.append(k)
    ric[idx][2]=[k+f"={v[1]}" for k,v in sorted(voci.items()) if v[1]]  # solo modelli con prezzo: le parole generiche portavano solo rumore
    print(ric[idx][0],len(gen),'generici +',len(voci),'dalla tabella;',len(' | '.join(ric[idx][2])),'caratteri')
json.dump(ric,open(D+'ricerche_prezzi.json','w'),indent=1,ensure_ascii=False)
if '--carica' in sys.argv:
    B='https://vinted-radar-production.up.railway.app'
    for qid,(n,u,m) in zip((129,130,131),ric):
        d={'query':u,'query_name':n+' :: '+' | '.join(m)}
        print(qid,urllib.request.urlopen(urllib.request.Request(B+f'/update_query/{qid}',data=urllib.parse.urlencode(d).encode(),method='POST'),timeout=40).status)
