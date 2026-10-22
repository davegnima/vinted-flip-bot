# Rigenera TUTTE le liste del radar con regole di specificita':
import os as _os; _QUI=_os.path.dirname(_os.path.abspath(__file__)); _REPO=_os.path.abspath(_os.path.join(_QUI,'..','..'))
# R1 nessuna chiave di una sola parola senza cifre; R2 righe con brand: brand nella chiave (una chiave per ogni grafia del brand);
# R3 giochi: console nella chiave, o titolo di 3+ parole, o "pokemon <edizione>"; R4 parole escluse della riga (meno le banwords) dopo '!'.
import sys,os,re,io,json,html,contextlib,urllib.request,urllib.parse
D=_QUI; sys.path.insert(0,D); import envbot
from bot import radar_matrice as rm
sys.argv_orig=sys.argv; sys.argv=['x']
with contextlib.redirect_stdout(io.StringIO()):
    import genera, singole, studio_prezzi
sys.argv=sys.argv_orig
B='https://vinted-radar-production.up.railway.app'
norm=lambda k:' '.join(rm._normalizza(k).split())
BAN={norm(w) for w in html.unescape(re.search(r'name="banwords"[^>]*value="([^"]*)"',urllib.request.urlopen(B+'/config',timeout=40).read().decode()).group(1)).split('|||') if w.strip()}
NON_PORTARE={'film','pellicola','pellicole'}  # "35mm film camera" e' il titolo tipico di una fotocamera
PIATTAFORME={'gamecube','game cube','n64','nintendo 64','snes','super nintendo','game boy','gameboy','gbc','gba','advance','ds','3ds','switch','wii','saturn','playstation','ps1','ps2','psp','mega drive','megadrive','dreamcast','nes','game watch'}
M=rm.carica_matrice()
def piattaforma(k): return any(re.search(rf'(^| ){p}( |$)',k) for p in PIATTAFORME)
ALIAS={'n64':['n64','nintendo 64'],'snes':['snes','super nintendo'],'super nintendo':['snes','super nintendo'],'gamecube':['gamecube'],
 'game boy color':['game boy color','gbc'],'gbc':['game boy color','gbc'],'game boy advance':['game boy advance','gba'],'gba':['game boy advance','gba'],
 'game boy':['game boy'],'saturn':['saturn'],'3ds':['3ds'],'ds':['nintendo ds'],'game watch':['game watch','game & watch'],'game & watch':['game watch','game & watch']}
def piattaforme_riga(r):
    m=norm(r['modello'])
    for k in sorted(ALIAS,key=len,reverse=True):
        if re.search(rf'(^| ){k}( |$)',m): return ALIAS[k]
    return []
def chiavi_riga(r):
    brands=[norm(b) for b in (r.get('brand_chiavi') or []) if norm(b)]
    out=[]
    for k in {norm(c) for c in r['chiavi']}:
        if not k: continue
        if brands and not any(set(b.split())<=set(k.split()) for b in brands):
            ks=[f"{b} {k}" for b in brands]
        else: ks=[k]
        var=[norm(v) for v in (r.get('parole_variante') or []) if norm(v)]
        if var: ks=[f"{x} {v}" for x in ks for v in var]   # riga 'completo in scatola': serve una parola di variante
        for k2 in ks:
            w=k2.split()
            if brands and len(set(w))<len(w) and any(set(w)==set(b.split()) for b in brands): continue
            gioco=r['radar']=='console_retro' and not brands
            generica=len(w)==1 and not re.search(r'\d',k2)
            if gioco and (generica or not (piattaforma(k2) or len(w)>=3 or (w[0]=='pokemon' and len(w)==2))):
                out+= [f"{k2} {p}" for p in piattaforme_riga(r)]   # R3: titolo + console della scheda
                continue
            if generica: continue                                                  # R1
            out.append(k2)
    return out
def prezzo(r):
    rv=r.get('rivendita_veloce_eur')
    if rv is None: return None
    bm=r['buy_max']; return f"{rv}/{0 if r.get('sotto_soglia') else ('?' if bm is None else bm)}"
MODERNE=['switch','nintendo switch','3ds','2ds','wii u','remake','remastered','ps4','ps5','xbox','nso']
REPRO=['custom','repro','reproduction','riproduzione','bootleg','homebrew']
ABITI=['bob','chapeau','cappello','hat','mutze','casquette','cap','beanie','t shirt','tshirt','tee shirt','maglietta','felpa','sweat','sweatshirt','hoodie','pullover','longsleeve','calzini','socks','pigiama','costume']
def escl(r):
    e=[norm(x) for x in r.get('parole_escluse') or []]
    if r['radar']=='console_retro':
        p=piattaforme_riga(r)
        if p and not any(x in ('3ds','nintendo ds') for x in p): e+=MODERNE
        e+=REPRO+ABITI+['starter pack']
    return [x for x in e if x and x not in BAN and x not in NON_PORTARE]
def da_matrice(sel):
    v={}
    for r in M:
        if not sel(r): continue
        p=prezzo(r)
        if not p: continue
        ex=','.join(escl(r))
        for k in chiavi_riga(r):
            if k not in v or r['rivendita_veloce_eur']<v[k][0]: v[k]=(r['rivendita_veloce_eur'],p+(f"!{ex}" if ex else ''))
    return {k:p for k,(_,p) in v.items()}
def con_brand(d,brand):
    out={}
    for k,p in d.items():
        k=norm(k)
        if not set(brand.split())<=set(k.split()): k=f"{brand} {k}"
        if len(k.split())==1 and not re.search(r'\d',k): continue
        out[k]=p
    return out
foto=lambda r: r['radar']=='fotografia'
F1={**da_matrice(lambda r: foto(r) and not genera.lente(r) and not genera.digitale(r))}
F2=da_matrice(lambda r: foto(r) and genera.lente(r))
F3=da_matrice(lambda r: foto(r) and genera.digitale(r))
for r in M:  # stime mie per le righe di fotografia senza venduti sufficienti
    if foto(r) and r.get('rivendita_veloce_eur') is None and genera.stima(r):
        rv=genera.stima(r); p=f"{rv}/{rm.buy_max(rv,r.get('spedizione_eur'),r.get('rischio_falsi'),r.get('rischio_guasti')) if rv>=100 else 0}*"
        tgt=F3 if genera.digitale(r) else (F2 if genera.lente(r) else F1)
        for k in chiavi_riga(r): tgt.setdefault(k,p)
F1.update({'nikon fm10':'60/0*','olympus om 10':'40/0*','olympus om10':'40/0*','olympus om 20':'50/0*','olympus om 2000':'50/0*','minolta dynax':'30/0*'})
mod=lambda m: (lambda r: r['radar']==m)
SORG={'F1 Analogiche':F1,'F2 Obiettivi':F2,'F3 Compatte digitali':F3,'G2 Lampade design':da_matrice(mod('illuminazione_design')),
 'G3 Audio':da_matrice(mod('audio')),'G5 Argento gioielli':da_matrice(mod('argento_gioielli')),'G6 Golf':da_matrice(mod('golf')),'G7 Collezionismo':da_matrice(mod('collezionismo'))}
COPIE_LEGO='lepin,compatibile,compatible,kompatibel,mould king,non originale,non lego,replica,moc,custom,incompleto,incompleta,incomplet,pezzi mancanti,mancano,tipo lego,stile lego,cada,bela'
def copie_lego(L):
    """Lego: niente copie, MOC e set incompleti (42143 a 45 EUR del 18/10)."""
    out={}
    for k,p in L.items():
        pz,_,ex=p.partition('!'); ex=[e for e in ex.split(',') if e]+[norm(e) for e in COPIE_LEGO.split(',')]
        out[k]=pz+'!'+','.join(dict.fromkeys(ex))
    return out
CONS=da_matrice(mod('console_retro')); BORSE=da_matrice(mod('borse_vintage')); LEGO=copie_lego(da_matrice(mod('lego'))); ARR=da_matrice(mod('arredo_design'))
BRAND_S={'C5 Game Boy Micro':'game boy micro','S27 PSP Go':'psp','S28 New 3DS XL':'3ds','S31 Walkman WM-D6C':'walkman','S32 Walkman DD':'walkman','S33 Sennheiser HD 600':'sennheiser','S34 Sennheiser HD 650':'sennheiser','S36 Technics 1200':'technics','S41 Louis Poulsen':'louis poulsen','S45 Seiko 6139':'seiko','S46 Montblanc 146 149':'montblanc','S50 Carhartt Detroit':'carhartt','S47a Arcteryx Beta':'arc teryx','S47b Arcteryx Alpha':'arc teryx','S47c Arcteryx Atom':'arc teryx','S49 TNF Nuptse 1996':'nuptse'}
GEN={'carte','pedale','orecchini','the','gathering','redline'}
TAB_STUDIO={'eames':'arredo_design','kartell':'arredo_design','flos':'illuminazione_design','artemide':'illuminazione_design','bang olufsen':'audio','leica':'fotografia','scotty cameron':'golf','lego':'lego','game boy':'console_retro','nintendo 64':'console_retro','persol':'occhiali','oliver peoples':'occhiali','cazal':'occhiali','matsuda':'occhiali','moscot':'occhiali'}
ACC={'psp':'gocam,go cam,camara,camera,kamera,fotocamera,umd,gioco,jeu,juego,spiel','chanel':'modello,modele,style,inspired','dior':'modello,modele,style','ysl':'modello,modele,style','carhartt':'shirt,t shirt,chemise,hemd,camicia,jeans,pantalon,pantaloni,hose,cap,beanie,mutze,berretto,cappello','kitchenaid':'blender,blenders,frullatore,mixeur,standmixer,ciotola,bol,schussel,frusta,fouet,gancio,crochet,accessorio,aufsatz,coperchio,couvercle','macbook':'tastiera,keyboard,clavier,tastatur,borsa,sacoche,sleeve,hub,dock,adattatore,display,schermo,ecran,bildschirm,scheda madre,logic board,speaker,altoparlante,ventola,ventole,fan,cerniera,trackpad','thermomix':'bol,boccale,boccali,mixtopf,plateau,varoma,coperchio,couvercle,deckel,lama,couteau,messer,spatola,spatule,decoupe,découpe,slider,cestello,panier,gareinsatz,libro,ricette,chip,cook key',
 'dyson':'brosse,brosses,spazzole,akkupack,bocchetta,filtro,filter,filtre,tubo,tube,rohr,spazzola elettrica,mini turbo,testina,embout,aufsatz,supporto da parete,wandhalterung',
 'smeg':'coperchio,couvercle,filtro,brocca,carafe',
 'dji':'propeller,propellerschutz,eliche,elica,hélices,helices,paraeliche,protezione,borsa,sac,tasche,custodia rigida,filtri nd,nd filter,landing',
 'gopro':'supporto,mount,fixation,halterung,custodia,gehäuse,boitier,caisson,stick,selfie,asta',
 'garmin':'cinturino,bracelet,armband,fascia,ceinture,brustgurt,supporto,halterung,cavo,chargeur',
 'apple watch':'cinturino,bracelet,armband,correa,pellicola,cover,case',
 'ipad':'tastiera,keyboard,clavier,tastatur,penna,stylus,pencil,stand,support,halterung,custodia,borsa',
 'kindle':'custodia,pochette,hülle,funda',
 'shimano':'pedale,pedali,pédales,pedals,mulinello,cassette,cassetta,catena,chain,kette,pattino,pastiglie,plaquettes,bremsbeläge',
 'campagnolo':'catena,chain,kette,pattino,pastiglie,cassetta,cassette',
 'oakley':'lenti,lens,verres,gläser,ricambio lenti,custodia,étui',
 'ray ban':'lenti,lens,verres,gläser,custodia,étui',
 'sonos':'supporto,stand,halterung,staffa,wandhalterung',
 'bose':'cuscinetti,ear pads,coussinets,polster',
 'sony wh 1000xm':'cuscinetti,ear pads,coussinets,polster,custodia,étui',
 'airpods pro':'boitier,boîtier,estuche,ladecase,custodia,étui,case,cover,singolo,single,gauche,droit,links,rechts,sinistro,destro',
 'airpods max':'boitier,estuche,custodia,étui,case,cover,cuscinetti,ear pads',
 'le creuset':'coperchio,couvercle,deckel,presina,manique',
 'staub':'coperchio,couvercle,deckel',
 'fender':'squier,custodia,gigbag,case,borsa,pickup,battipenna,pickguard,manico,neck,ponte',
 'gibson':'custodia,gigbag,case,pickup,battipenna,pickguard,manico,neck,ponte,epiphone',
 'technics':'braccio,tonearm,piatto,plateau,coperchio,dust cover,testina,headshell,cinghia,puntina'}
# 4h del 18/10: con le chiavi 'switch oled', 'airpods pro 2', 'dyson airwrap' passavano scatole, custodie, cinturini, pellicole, spazzole, gommini
ACC_GEN=('housse,pochette,funda,fundas,tasche,hulle,etui,schutzglas,schutzfolie,vetro temperato,pellicola protettiva,film protection,protection,'
 'bracelet,bracelets,bracciale,cinturino,cinturini,armband,correa,strap,almohadillas,cuscinetti,pontas,eartips,gommini,embouts,'
 'caricatore,chargeur,charger,ladegerat,cargador,dock,docking,hub,supporto,halterung,'
 'filtro,filtri,filter,filtres,filtre,spazzola,brush,brosse,burste,escova,'
 'accessorio,accessoire,accessoires,accessory,accessories,accesorios,zubehor,aufsatz,aufsatze,attachment,'
 'kopfstutze,ecran,schermo,screen,tapa,coperchio,lame,lames,blade,plaque,pin,keyring,portachiavi,'
 'boite,caja,packaging,verpackung,aufbewahrungsbox,joy con,controller,guitar hero,'
 'kinder,kids,enfant,bambino,bambina,junior,youth').split(',')
for _k,_v in {'shimano':'disque,disc,disco,rotor,frein,freno,bremse,brake,plateau,chainring,corona,pedivela,guarnitura,crankset,crankstel,kurbel,pedalier,pedalen,pedales,pedal,deragliatore,derailleur,schaltwerk,umwerfer,leve,levier,comandi,shifter,mozzo,hub,ruota,ruote,wheel,roue,cerchio,pignone,scheibenbremsbelage,bremsbelage,pads','campagnolo':'disque,disc,disco,rotor,frein,freno,bremse,brake,plateau,chainring,corona,pedivela,guarnitura,crankset,crankstel,kurbel,pedalier,pedalen,pedales,pedal,deragliatore,derailleur,schaltwerk,umwerfer,leve,levier,comandi,shifter,mozzo,hub,ruota,ruote,wheel,roue,cerchio,pignone,scheibenbremsbelage,bremsbelage,pads',
  'dji':'mic,microfono,micro,objectif,obiettivo,lumiere,luce,light,base,carga,batteria,bateria,batterie,battery,akku,elica,eliche,propeller,helice',
  'dyson':'batteria,bateria,batterie,battery,akku,kit,duse,turbinenduse,matratzenduse,fonaufsatz,toelettatura,tubo,rohr,tube,testina,beccuccio',
  'thermomix':'livre,buch,rezepte,kochbuch,magazine,rivista,revista,saveurs,ricettario',
  'steam deck':'lot,entretien,skin,grip',
  'switch oled':'voor,skin,grip,custodia',
  'persol':'lenti,lens,verres,glaser'}.items():
    ACC[_k]=(ACC.get(_k,'')+','+_v).strip(',')
ACC_GEN+=['voor','mic','microfono']
# 8h del 18/10: basi e supporti Dyson, lame Thermomix, pistoncini e catene Shimano, copie dichiarate, starter pack 3DS, cappelli Pikachu
for _k,_v in {'dyson':'stander,staender,station,base,pouch,support,custodia,ricarica',
  'thermomix':'mariposa,mariposas,farfalla,cuchilla,cuchillas,cuchillo,vervangmes,mes,topf,boccale',
  'shimano':'piston,pistons,pistoncini,chaine,catena,kette,chain','campagnolo':'piston,pistons,chaine,catena,kette'}.items():
    ACC[_k]=(ACC.get(_k,'')+','+_v).strip(',')
ACC_GEN+=['geen origineel','nicht original','non originale','non original','no original','pas original','starter pack','bacelets']
def accessori(L,brand,chiave,gen=True):
    extra=[f"per {brand}",f"pour {brand}",f"für {brand}",f"for {brand}","compatibile","compatible","kompatibel"]+(ACC_GEN if gen else [])+[x for x in (ACC.get(chiave,'')+','+ACC.get(brand,'')).split(',') if x]
    out={}
    for k,p in L.items():
        pz,_,ex=p.partition('!'); ex=[e for e in ex.split(',') if e]+[norm(e) for e in extra]
        out[k]=pz+'!'+','.join(dict.fromkeys(ex))
    return out
def lista_per(nome,url=''):
    if nome in SORG: return SORG[nome]
    if nome.startswith('G1'): return CONS
    if nome.startswith('G4'): return BORSE
    if nome.startswith('H Lego'): return LEGO
    if nome.startswith('H Arredo'): return ARR
    if nome in BRAND_S: return accessori(con_brand(singole.L[nome],BRAND_S[nome]),BRAND_S[nome],BRAND_S[nome])
    if nome.startswith('STUDIO'):
        kw=nome.split(' ',2)[2]
        st=urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get('search_text',[kw])[0]
        brand=' '.join(w for w in norm(st).split() if w not in GEN)
        base=da_matrice(mod(TAB_STUDIO[kw])) if kw in TAB_STUDIO else {}
        stime={k:p for k,p in studio_prezzi.S.get(kw,{}).items() if p.endswith('*')}
        out=accessori({**base,**con_brand(stime,brand)},brand,kw,gen=not nome.startswith(('STUDIO bijoux','STUDIO occhiali')))
        if nome.startswith(('STUDIO giochi','STUDIO elettronica','STUDIO casa','STUDIO musica')):
            out={k:p+(',' if '!' in p else '!')+','.join(ABITI) for k,p in out.items()}
        return out
    return None
def componi(L):
    """Parole escluse presenti in almeno meta' delle voci: una volta sola in testa ('!...')."""
    import collections
    c=collections.Counter(w for p in L.values() if '!' in p for w in set(p.split('!',1)[1].split(',')))
    comuni=sorted(w for w,n in c.items() if n>=len(L)/2)
    voci=[]
    for k,p in sorted(L.items()):
        pz,_,ex=p.partition('!'); ex=[w for w in ex.split(',') if w and w not in comuni]
        voci.append(f"{k}={pz}"+(f"!{','.join(ex)}" if ex else ''))
    return ' | '.join(([ '!'+','.join(comuni)] if comuni else [])+voci)
t=urllib.request.urlopen(B+'/queries',timeout=40).read().decode(); rep=[]; COMPOSTI={}
for m in re.finditer(r'action="/update_query/(\d+)"(.*?)</form>',t,flags=re.S):
    qid=m.group(1); q=html.unescape(re.search(r'name="query"[^>]*value="([^"]*)"',m.group(2)).group(1))
    vecchio=html.unescape(re.search(r'name="query_name"[^>]*value="([^"]*)"',m.group(2)).group(1)); nome=vecchio.split(' :: ')[0]
    L=lista_per(nome,q)
    if L is None: rep.append((nome,'NESSUNA SORGENTE',0,0)); continue
    nuovo=nome+' :: '+componi(L)
    vk={e.split('=')[0].strip() for e in vecchio.split(' :: ',1)[1].split('|')} if ' :: ' in vecchio else set()
    rep.append((nome,len(L),len(vk-set(L)),len(nuovo))); COMPOSTI[nome]=(vecchio,nuovo)
    if '--carica' in sys.argv:
        urllib.request.urlopen(urllib.request.Request(B+f'/update_query/{qid}',data=urllib.parse.urlencode({'query':q,'query_name':nuovo}).encode(),method='POST'),timeout=60)
json.dump({n:sorted(lista_per(n) or {}) for n,*_ in rep},open(os.path.join(D,'chiavi_nuove.json'),'w'),ensure_ascii=False,indent=0)
json.dump(COMPOSTI,open(os.path.join(D,'composti.json'),'w'),ensure_ascii=False)
for r in rep: print(r)
