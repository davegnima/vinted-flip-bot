# Sostituisce G1 (console) e G4 (borse) con ricerche per famiglia/brand: le categorie intere superano 20 annunci ogni 15 s.
import re,html,urllib.request,urllib.parse
B='https://vinted-radar-production.up.railway.app'
t=urllib.request.urlopen(B+'/queries',timeout=40).read().decode()
q={}
for m in re.finditer(r'action="/update_query/(\d+)"(.*?)</form>',t,flags=re.S):
    n=html.unescape(re.search(r'name="query_name"[^>]*value="([^"]*)"',m.group(2)).group(1)); q[n.split(' :: ')[0]]=(m.group(1),n)
CONS='catalog[]=3026&catalog[]=3025&catalog[]=3027'; BORSE='catalog[]=158&catalog[]=156'
NUOVE={'G1':[('G1a Pokemon','pokemon',170),('G1b Game Boy','game boy',330),('G1c Zelda','zelda',100),('G1d Game & Watch','game watch',90),
             ('G1e 3DS','3ds',190),('G1f Super Nintendo','super nintendo',110),('G1g SNES','snes',110),('G1h N64','n64',130),
             ('G1i Nintendo 64','nintendo 64',130),('G1j GameCube','gamecube',80),('G1k Saturn','saturn',280)],
       'G4':[('G4a Loewe','loewe',170),('G4b Bottega Veneta','bottega veneta',170),('G4c Mulberry','mulberry',170)]}
for vecchia,cat in (('G1 Console retro',CONS),('G4 Borse vintage',BORSE)):
    qid,nome=q[vecchia]; lista=nome.split(' :: ',1)[1]
    for disp,testo,pt in NUOVE[vecchia[:2]]:
        url=f"https://www.vinted.it/catalog?search_text={urllib.parse.quote_plus(testo)}&{cat}&price_to={pt}&currency=EUR&order=newest_first"
        r=urllib.request.urlopen(urllib.request.Request(B+'/add_query',data=urllib.parse.urlencode({'query':url,'query_name':disp+' :: '+lista}).encode(),method='POST'),timeout=40)
        print(disp,r.status)
    print('tolgo',vecchia,urllib.request.urlopen(urllib.request.Request(B+f'/remove_query/{qid}',method='POST'),timeout=40).status)
t=urllib.request.urlopen(B+'/queries',timeout=40).read().decode(); print('ricerche ora:',len(set(re.findall(r'update_query/(\d+)',t))))
