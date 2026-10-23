# Aggiunge un catalog id (categoria Vinted) alle ricerche STUDIO: niente piu' cover, custodie e ricambi nei risultati.
# Verificato il 23/10 con ricerche di prova (scansione di id con una parola di ricerca):
#  - il testo con piu' parole + catalog[] FUNZIONA (verificato il 23/10: 'switch oled'+3025, 'airpods pro'+3678 danno annunci veri);
#    il '0 annunci' visto prima era una lettura troppo anticipata della prova, non un limite;
#  - 3025 console, 3678 cuffie, 3681 altoparlanti, 3035/3004 smartwatch, 3031 fitness tracker, 3074 action camera, 3075/3076 fotocamere;
#  - gli id 23xx dell'albero "Intrattenimento" (es. 2420 Switch console) NON filtrano (0 annunci); gli id di Casa (es. 1940 vasi) si.
# Uso: python3 catalogo.py [--carica]
import sys,re,html,urllib.request,urllib.parse
B='https://vinted-radar-production.up.railway.app'
MAPPA={  # nome ricerca -> (parola di ricerca, id catalogo)
 'STUDIO elettronica switch oled':('switch oled',[3025]),
 'STUDIO elettronica steam deck':('steam deck',[3025]),
 'STUDIO elettronica ps vita':('ps vita',[3025]),
 'STUDIO elettronica airpods pro':('airpods pro',[3678]),
 'STUDIO elettronica airpods max':('airpods max',[3678]),
 'STUDIO elettronica bose':('bose',[3678,3681]),
 'STUDIO elettronica sony wh 1000xm':('sony wh 1000xm',[3678]),
 'STUDIO elettronica marshall':('marshall',[3678,3681]),
 'STUDIO elettronica sonos':('sonos',[3681]),
 'STUDIO elettronica apple watch':('apple watch',[3035,3004]),
 'STUDIO elettronica garmin':('garmin',[3035,3004,3031]),
 'STUDIO elettronica gopro':('gopro',[3074]),
 'STUDIO elettronica polaroid':('polaroid',[3076,3075]),
 'STUDIO elettronica instax':('instax',[3076,3075]),
 'STUDIO casa richard ginori':('ginori',[1958, 1959, 1960, 1961, 2006, 2007, 2008, 2009, 2010, 2011, 1940, 1957]),
 'STUDIO casa royal copenhagen':('royal copenhagen',[1958, 1959, 1960, 1961, 2006, 2007, 2008, 2009, 2010, 2011, 1940, 1957]),
 'STUDIO casa arabia finland':('arabia',[1958, 1959, 1960, 1961, 2006, 2007, 2008, 2009, 2010, 2011, 1940, 1957]),
 'STUDIO casa iittala':('iittala',[1958, 1959, 1960, 1961, 2006, 2007, 2008, 2009, 2010, 2011, 1940, 1957]),
 'STUDIO casa bitossi':('bitossi',[1940, 1959, 1960, 1961, 1957]),
 'STUDIO casa venini':('venini',[1940, 1957, 2008, 2009, 2010, 2011, 1964, 3836, 3837, 3838, 3839]),
 'STUDIO casa murano':('murano',[1940, 1957, 2008, 2009, 2010, 2011, 1964, 3836, 3837, 3838, 3839]),
 'STUDIO casa tom dixon':('tom dixon',[3836, 3837, 3838, 3839, 1957]),
 'STUDIO casa flos':('flos',[3836, 3837, 3838, 3839]),
 'STUDIO casa artemide':('artemide',[3836, 3837, 3838, 3839]),
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
    nuovo=f"https://www.vinted.it/catalog?search_text={urllib.parse.quote(txt)}&"+''.join(f'catalog[]={i}&' for i in ids)+f"price_to={pt}&currency=EUR&order=newest_first"
    print(qid,k,'\n   ',u,'\n -> ',nuovo)
    if '--carica' in sys.argv:
        urllib.request.urlopen(urllib.request.Request(B+f'/update_query/{qid}',data=urllib.parse.urlencode({'query':nuovo,'query_name':n}).encode(),method='POST'),timeout=60)
