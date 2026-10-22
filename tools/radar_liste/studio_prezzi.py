# Liste con prezzo per le ricerche STUDIO: tabella del bot dove c'e', altrimenti stime mie (rivendita veloce, '*').
import os as _os; _QUI=_os.path.dirname(_os.path.abspath(__file__)); _REPO=_os.path.abspath(_os.path.join(_QUI,'..','..'))
import sys,re,html,json,urllib.request,urllib.parse
sys.path.insert(0,_QUI); import envbot
from bot import radar_matrice as rm
M=rm.carica_matrice(); norm=lambda k:' '.join(rm._normalizza(k).split())
def tab(*mods):
    v={}
    for r in M:
        if r['radar'] not in mods or not r.get('rivendita_veloce_eur'): continue
        bm=r['buy_max']; pz=f"{r['rivendita_veloce_eur']}/{0 if r.get('sotto_soglia') else ('?' if bm is None else bm)}"
        for k in r['chiavi']:
            k=norm(k)
            if k not in v or r['rivendita_veloce_eur']<v[k][0]: v[k]=(r['rivendita_veloce_eur'],pz)
    return {k:p for k,(_,p) in v.items()}
def st(d,sped=6):
    out={}
    for ks,rv in d.items():
        p=f"{rv}/{rm.buy_max(rv,sped,1,2) if rv>=100 else 0}*"
        for k in ks.split('|'): out[norm(k)]=p
    return out
S={
'alessi':st({'9093':70,'plisse':60,'bombe':60,'juicy salif':50,'anna g':30}),
'smeg':st({'tostapane|toaster':70,'bollitore|kettle':60,'frullatore|blender':80,'planetaria|impastatrice':250,'macchina caffe|espresso':150},8),
'kitchenaid':st({'artisan':220,'planetaria|impastatrice':200,'kitchenaid mini':150,'frullatore|blender':70},10),
'le creuset':st({'cocotte':90,'le creuset 24':100,'le creuset 28':120,'le creuset 20':70},10),
'staub':st({'cocotte':80,'staub 24':90},10),
'dyson':st({'v15':300,'v11':180,'v10':130,'v8':80,'airwrap':250,'supersonic':180,'dyson pure':150},10),
'thermomix':st({'tm6':700,'tm5':380,'tm31':180},12),
'iittala':st({'aalto':60,'toikka':90,'kastehelmi':25,'taika':20}),
'rosenthal':st({'versace':80,'wiinblad':60,'studio line':40}),
'villeroy boch':st({'acapulco':40,'villeroy boch':20}),
'richard ginori':st({'gio ponti':150,'ginori 1735':40,'ginori vaso':60}),
'venini':st({'fazzoletto':250,'venini vaso':200,'venini':150}),
'murano':st({'sommerso':70,'seguso':120,'barovier':150,'salviati':80,'murano vaso':50}),
'royal copenhagen':st({'blue fluted|musselmalet':40,'royal copenhagen':40}),
'arabia finland':st({'paratiisi':50,'ruska':25,'valencia':40}),
'bitossi':st({'rimini blu':70,'aldo londi':90,'bitossi':60}),
'tom dixon':st({'melt':250,'beat':200,'tom dixon':120},10),
'hay':st({'hay':40}),'muuto':st({'muuto':60}),
'herman miller':{**st({'aeron':450,'mirra':300,'sayl':250},15),**tab('arredo_design')},
'eames':tab('arredo_design'),'kartell':tab('arredo_design'),'flos':tab('illuminazione_design'),'artemide':tab('illuminazione_design'),
'bose':st({'qc45':130,'qc35':80,'quietcomfort ultra':220,'soundlink':70,'bose 700':150}),
'sonos':st({'sonos one':100,'sonos five':300,'sonos arc':450,'sonos beam':250,'sonos move':250,'sonos roam':100,'sonos sub':400},10),
'marshall':st({'stanmore':180,'acton':130,'woburn':250,'emberton':90,'kilburn':130,'major':50},10),
'airpods max':st({'airpods max':330}),'airpods pro':st({'airpods pro 2':140,'airpods pro':90}),
'ipad':st({'ipad pro m1|ipad pro 2021':550,'ipad pro m2|ipad pro 2022':700,'ipad pro 2020':400,'ipad air 4':280,'ipad air 5|ipad air m1':380,'ipad air m2':480,'ipad mini 6':300}),
'macbook':st({'macbook air m1':450,'macbook air m2':650,'macbook air m3':800,'macbook pro m1':650,'macbook pro m2':850,'macbook pro m3':1100},8),
'apple watch':st({'apple watch ultra':400,'series 9':230,'series 8':190,'series 7':150}),
'kindle':st({'paperwhite':70,'kindle oasis':110,'kindle scribe':200}),
'switch oled':st({'switch oled':220},8),'steam deck':st({'steam deck oled':450,'steam deck':320},8),
'ps vita':st({'ps vita slim|ps vita 2000|pch 2000|pch 2004':120,'ps vita oled|ps vita 1000|pch 1000|pch 1004':110,'ps vita console':110}),
'gopro':st({'hero 12':250,'hero 11':200,'hero 10':160,'hero 9':130,'hero 8':100}),
'dji':st({'mini 4 pro':550,'mini 3':300,'dji mini 2':220,'osmo pocket 3':380,'osmo pocket':120,'osmo action':150}),
'garmin':st({'fenix 7':350,'fenix 6':220,'forerunner 955':280,'forerunner 255':160,'epix':400,'edge 530':150,'edge 830':200}),
'sony wh 1000xm':st({'1000xm5|xm5':220,'1000xm4|xm4':150,'1000xm3|xm3':90}),
'bang olufsen':tab('audio'),
'polaroid':{**tab('fotografia'),**st({'polaroid 600':40,'polaroid now':60,'polaroid i 2':350})},
'instax':st({'mini evo':120,'instax wide':60,'mini 90':80,'instax mini':40}),
'leica':tab('fotografia'),
'shimano':st({'dura ace':300,'ultegra':150,'shimano 105':80,'xtr':250,'deore xt':100,'stradic':120,'stella':350}),
'campagnolo':st({'super record':400,'campagnolo record':250,'chorus':150,'bora':600,'shamal':300}),
'salomon':st({'xt 6':110,'s lab':120,'speedcross':60,'acs':80}),
'la sportiva':st({'solution':70,'tc pro':80,'skwama':60,'katana':50}),
'black diamond':st({'camalot':50}),'petzl':st({'grigri':60,'petzl nao':100}),
'burton':st({'burton custom':200,'step on':180},12),
'oakley':st({'frogskins':70,'juliet':250,'mars':200,'penny':200,'x metal':200,'radar ev':90,'sutro':80}),
'titleist':{**tab('golf'),**st({'t100':500,'tsr':250},12)},'scotty cameron':tab('golf'),
'babolat':st({'pure aero':120,'pure drive':110,'pure strike':110},8),
'warhammer':st({'combat patrol':90}),'magic the gathering':st({'booster box':110,'commander deck':40}),
'pokemon carte':st({'display':130,'booster box':110,'elite trainer box':55}),'yu gi oh':st({'booster box|display':80}),
'hot wheels redline':st({'redline':60}),'lego':tab('lego'),'game boy':tab('console_retro'),'nintendo 64':tab('console_retro'),
'vinile':{},
'fender':st({'stratocaster':500,'telecaster':500,'jazz bass':500,'precision bass':500,'squier':150,'blues junior':350,'hot rod':400},15),
'gibson':st({'les paul':1200,'gibson sg':700,'es 335':2000,'epiphone':200},15),
'roland':st({'juno':800,'jd xi':250,'td 17':600,'boutique':250,'sp 404':300,'tb 03':250},12),
'korg':st({'minilogue':300,'volca':110,'ms 20':400,'monologue':200,'microkorg':250,'opsix':450},12),
'moog':st({'subsequent':900,'mother 32':450,'grandmother':600,'minitaur':300},12),
'boss pedale':st({'ds 1':40,'bd 2':60,'boss rc':100,'boss dd':80,'metal zone':50,'boss rv':100}),
'technics':st({'sl 1200|sl1200':400,'sl 1210|sl1210':400,'sl bd':80},15),
'marantz':st({'2226':500,'2230':600,'2270':900,'marantz pm':150,'marantz cd':80},15),
'revox':st({'b77':500,'a77':450,'pr99':700,'b215':250},15),
'persol':tab('occhiali'),'ray ban':{**tab('occhiali'),**st({'bausch lomb|b l':120,'wayfarer':70,'aviator':70,'clubmaster':70})},
'oliver peoples':tab('occhiali'),'cazal':tab('occhiali'),'matsuda':tab('occhiali'),'moscot':tab('occhiali'),
'chanel orecchini':{**tab('bijoux_vintage'),**st({'chanel orecchini|chanel boucles|chanel earrings|chanel ohrringe|chanel pendientes':250,'chanel collana|chanel collier|chanel necklace|chanel kette|chanel collar':350,'chanel spilla|chanel broche|chanel brooch|chanel brosche':300})},
'dior orecchini':st({'dior orecchini|dior boucles|dior earrings|dior ohrringe|dior pendientes':150,'dior collana|dior collier|dior necklace|dior kette|dior collar':200}),'ysl orecchini':st({'ysl orecchini|ysl boucles|ysl earrings|ysl ohrringe|ysl pendientes|saint laurent orecchini|saint laurent boucles':150}),
'lacroix':{**tab('bijoux_vintage'),**st({'lacroix orecchini':120})},'swarovski':st({'swarovski':40}),'pandora':st({'pandora':30}),
}
B='https://vinted-radar-production.up.railway.app'
t=urllib.request.urlopen(B+'/queries',timeout=40).read().decode(); n_ok=0; vuote=[]
for m in re.finditer(r'action="/update_query/(\d+)"(.*?)</form>',t,flags=re.S):
    qid=m.group(1); q=html.unescape(re.search(r'name="query"[^>]*value="([^"]*)"',m.group(2)).group(1))
    nome=html.unescape(re.search(r'name="query_name"[^>]*value="([^"]*)"',m.group(2)).group(1)).split(' :: ')[0]
    if not nome.startswith('STUDIO'): continue
    kw=nome.split(' ',2)[2]; L=S.get(kw)
    if L is None: print('MANCA',kw); continue
    if not L: vuote.append(kw); continue
    n_ok+=1
    if '--carica' in sys.argv:
        d={'query':q,'query_name':nome+' :: '+' | '.join(f"{k}={p}" for k,p in sorted(L.items()))}
        urllib.request.urlopen(urllib.request.Request(B+f'/update_query/{qid}',data=urllib.parse.urlencode(d).encode(),method='POST'),timeout=40)
print(n_ok,'ricerche studio con lista; senza lista:',vuote)
