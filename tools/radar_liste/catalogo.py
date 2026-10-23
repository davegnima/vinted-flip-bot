# Aggiunge un catalog id (categoria Vinted) alle ricerche STUDIO: niente piu' cover, custodie e ricambi nei risultati.
# Verificato il 23/10 con ricerche di prova (scansione di id con una parola di ricerca):
#  - il testo di ricerca con DUE parole + catalog[] restituisce 0 annunci (il tracker manda 'a+b' come un unico termine): con il catalogo
#    si usa UNA parola e la lista modelli del nome filtra il resto;
#  - 3025 console, 3678 cuffie, 3681 altoparlanti, 3035/3004 smartwatch, 3031 fitness tracker, 3074 action camera, 3075/3076 fotocamere;
#  - gli id 23xx dell'albero "Intrattenimento" (es. 2420 Switch console) NON filtrano (0 annunci); gli id di Casa (es. 1940 vasi) si.
# Uso: python3 catalogo.py [--carica]
import sys,re,html,urllib.request,urllib.parse
B='https://vinted-radar-production.up.railway.app'
MAPPA={  # nome ricerca -> (parola di ricerca, id catalogo)
 'STUDIO elettronica switch oled':('switch',[3025]),
 'STUDIO elettronica steam deck':('steam',[3025]),
 'STUDIO elettronica ps vita':('vita',[3025]),
 'STUDIO elettronica airpods pro':('airpods',[3678]),
 'STUDIO elettronica airpods max':('airpods',[3678]),
 'STUDIO elettronica bose':('bose',[3678,3681]),
 'STUDIO elettronica sony wh 1000xm':('sony',[3678]),
 'STUDIO elettronica marshall':('marshall',[3678,3681]),
 'STUDIO elettronica sonos':('sonos',[3681]),
 'STUDIO elettronica apple watch':('watch',[3035,3004]),
 'STUDIO elettronica garmin':('garmin',[3035,3004,3031]),
 'STUDIO elettronica gopro':('gopro',[3074]),
 'STUDIO elettronica polaroid':('polaroid',[3076,3075]),
 'STUDIO elettronica instax':('instax',[3076,3075]),
}
def leggi():
    t=urllib.request.urlopen(B+'/queries',timeout=120).read().decode()
    for m in re.finditer(r'action="/update_query/(\d+)"(.*?)</form>',t,flags=re.S):
        n=html.unescape(re.search(r'name="query_name"[^>]*value="([^"]*)"',m.group(2)).group(1))
        u=html.unescape(re.search(r'name="query"[^>]*value="([^"]*)"',m.group(2)).group(1))
        yield m.group(1),n,u
for qid,n,u in leggi():
    k=n.split(' :: ')[0]
    if k not in MAPPA: continue
    txt,ids=MAPPA[k]
    pt=re.search(r'price_to=(\d+)',u).group(1)
    nuovo=f"https://www.vinted.it/catalog?search_text={txt}&"+''.join(f'catalog[]={i}&' for i in ids)+f"price_to={pt}&currency=EUR&order=newest_first"
    print(qid,k,'\n   ',u,'\n -> ',nuovo)
    if '--carica' in sys.argv:
        urllib.request.urlopen(urllib.request.Request(B+f'/update_query/{qid}',data=urllib.parse.urlencode({'query':nuovo,'query_name':n}).encode(),method='POST'),timeout=60)
