# Banwords del radar: lista corrente meno quelle che tagliano annunci buoni, piu' le nuove (5 lingue).
import os as _os; _QUI=_os.path.dirname(_os.path.abspath(__file__)); _REPO=_os.path.abspath(_os.path.join(_QUI,'..','..'))
import sys,re,html,urllib.request,subprocess
B='https://vinted-radar-production.up.railway.app'
cur=html.unescape(re.search(r'name="banwords"[^>]*value="([^"]*)"',urllib.request.urlopen(B+'/config',timeout=40).read().decode()).group(1)).split('|||')
TOGLI={'mount','batteria','batterie','accessori','accessoires'}  # 'mount' prende 'mountain'; batteria/batterie sono anche le batterie (strumento)
NUOVE='''mount adapter|batteria per|batteria di ricambio|batteria ricaricabile|batterie pour|batterie de rechange|batterie externe|ersatzakku|bateria para
per pezzi|per ricambi|pezzi di ricambio|for parts|for spares|spares or repair|pour pièces|pour pieces|hors service|für bastler|bastler|defekt|defect|guasto|guasta|non funzionante|non funziona|not working|doesn't work|ne fonctionne pas|ne marche pas|kaputt|rotto|rotta|cassé|cassee|averiado|no funciona|da riparare|à réparer|a reparar|zu reparieren|pour réparation
inspired|ispirat|ispirazione|stile |dupe|simil |similaire|ähnlich|imitación|non originale|not original|nicht original|pas original|no original|fake|contraffatt|reproduction|riproduzione|nachbildung|réplique|replik|copy
étui|hülle|funda |pellicola protettiva|screen protector|protection écran|vetro temperato|panzerglas|alimentatore|netzteil|cargador|ladekabel|ladegerät|supporto per|support pour|halterung|soporte para|sticker|adesivo|aufkleber|pegatina|skin per|cinturino|armband für|correa para|telecomando|fernbedienung|télécommande|mando a distancia|borsa fotografica|camera bag|kameratasche|sac photo
scatola originale vuota|boîte seule|boite seule|caja vacía|caja vacia|solo caja|nur verpackung|solo confezione|confezione vuota|catalogo|catalogue|katalog|brochure|depliant|rivista|magazine|prospekt|poster|affiche|locandina|flyer
giocattolo|jouet|spielzeug|juguete|miniatura|miniature|calamita|magnete|t-shirt|tshirt|t shirt|maglietta|peluche|plüsch|cuscino|kissen|coussin|cojín|federa|housse de coussin
accessori per|solo accessori|accessoires pour|accessories for|zubehör für|accesorios para|cerco |cherche |suche |busco |compro |scambio|échange|tausch|intercambio|prenotato|réservé|reserviert|reservado|reserved'''.replace('\n','|').split('|')
nuova=[w for w in cur if w.strip() and w.strip() not in TOGLI]
for w in NUOVE:
    if w and w not in nuova: nuova.append(w)
print(len(cur),'->',len(nuova))
if '--carica' in sys.argv:
    print(subprocess.run(['python3','-I',_QUI+'/cfg_tool.py','imposta','banwords='+'|||'.join(nuova)],capture_output=True,text=True).stdout[-200:])
BUONI="""Leica M6 TTL corpo|Canon AE-1 Program con 50mm|The North Face Mountain Jacket|Nikon F3 HP|Contax T2 titanio|Fujifilm X100V|Roland TD-17 batteria elettronica|Batterie électronique Roland TD-17|Sonos One|Dyson V11 Absolute|KitchenAid Artisan rossa|Le Creuset cocotte 24|Venini vaso fazzoletto|Lego Star Wars 75192 Millennium Falcon UCS|Game Boy Color edizione Pokémon|Arc'teryx Beta AR jacket|Seiko 6139 Pogue|Montblanc 149|Herman Miller Aeron|Chanel orecchini vintage CC|Ray-Ban Bausch & Lomb Wayfarer|Oakley Juliet|Fender Stratocaster Made in Mexico|Gibson Les Paul Studio|Korg Minilogue|Boss RC-30 Loop Station|Marantz 2226B|Pokemon display booster box sealed|Macbook Air M1 8GB|iPad Air 4 64GB|Garmin Fenix 7|DJI Mini 3|Shimano Ultegra groupset|Mulberry Bayswater|Loewe Amazona|Sennheiser HD 600|Sony Walkman WM-DD|Technics SL-1200 MK2|Polaroid SX-70 Land Camera|Rolleiflex 2.8F|Hasselblad 500C/M con Planar 80|TNF Nuptse 1996 Retro|Carhartt Detroit jacket|Leica Summicron 50mm f2|Zeiss Planar 50 1.4 Contax|Konica Hexar AF|Olympus mju II|Yashica T4 Super|Nintendo Switch OLED|Steam Deck 512GB|Apple Watch Ultra|Bose QC45|Marshall Stanmore II|Alessi 9093 bollitore|Smeg tostapane|Canon EF 70-200 f4 L USM|Burton Custom snowboard|Thermomix TM6 con accessori originali|Lampada Artemide Tolomeo originale|Vitra Eames Elephant|Kartell Componibili|Flos Arco|Le Creuset Signature|Iittala Aalto vaso|Moog Mother 32|Revox B77 bobine|Marantz PM 6006|GoPro Hero 11 Black|Dyson Supersonic|Pentax 67 con 105mm|Bottega Veneta intrecciato|New Nintendo 3DS XL|Game Boy Micro|PSP Go nera""".split('|')
if '--test' in sys.argv:
    for t in BUONI:
        hit=[w for w in nuova if w.strip() and w.strip().lower() in t.lower()]
        if hit: print('ESCLUSO:',t,'<-',hit)
    print('controllati',len(BUONI))
