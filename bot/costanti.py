"""Modulo estratto da main_telethon.py (spostamento meccanico)."""


# ---- fine import ----
# BLOCKLIST VENDITORI
VENDITORI_BLOCKLIST = {"valeryepippo", "firmadonna98", "cicciodonna779", "hadourif"}

# BLOCKLIST BRAND -- esclusione totale su richiesta esplicita dell'utente,
# indipendentemente da prezzo/margine/ROI stimati. "escludi intrend sempre.
# Non lo comprerò mai" (2026-09-20): a differenza delle regole di linea/era
# sopra (che abbassano il valore di una sottolinea ma valutano comunque il
# capo), un brand in questa lista non viene MAI comprato, quindi non ha
# senso nemmeno stimarne il prezzo di rivendita -- si scarta prima ancora
# di chiamare l'occhio, come un venditore in blocklist.
BRAND_BLOCKLIST = {"intrend"}

VINTED_BRAND_IDS = {
    # 1/11 boutique/contemporary (lista dell'utente): id letti da vinted.it/.com/brand/<id> via ricerca web, NON verificati sul sito
    # 1/11 (terzo giro: id trovati da un agente con la ricerca web, 4 su 4 controllati a campione; non verificati sul sito)
    "by walid": "3656179",
    "l.a.m.b.": "70010",
    "erdem": "330469",
    "emilia wickstead": "3170657",
    "rosie assoulin": "4825966",
    "agua bendita": "149418",
    "borgo de nor": "3250054",
    "leo lin": "7255280",
    "alémais": "5251547",
    "alemais": "5251547",
    "juliet dunn": "385800",
    "celia b": "2945216",
    "banjanan": "5507913",
    "ciao lucia": "4685553",
    "posse": "617825",
    "hill house home": "7311533",
    "the great": "393670",
    "antik batik": "744",
    "farm rio": "456895",
    "pink city prints": "4519561",
    "cleobella": "557035",
    "coach": "6721",
    "quince": "1356899",
    "oleana": "845100",
    "arc'teryx": "319730",
    "taylor stitch": "758477",
    "pistola": "1103107",
    "alex mill": "2286402",
    "mini rodini": "337720",
    "dragon diffusion": "1439172",
    "jérôme dreyfuss": "6383",
    "kurt geiger": "4733",
    "radley": "278167",
    "mz wallace": "525211",
    "volcom": "66",
    "champion": "7973",
    "bebe": "4443",
    "victoria's secret": "1185",
    "lucky brand": "42337",
    "sézane": "38437",
    "filson": "314367",
    "anthropologie": "73426",
    "mother": "258008",
    "citizens of humanity": "67850",
    "free people": "4983",
    "ganni": "170650",
    "stone island": "73306",
    # 1/11 (secondo giro, stesso metodo: id da ricerca web, non verificati)
    "johnny was": "293108", "gudrun sjödén": "4691067", "gudrun sjoden": "4691067", "madhappy": "5100236",
    "henry beguelin": "203938",
    "lancel": "2827",
    "double d ranch": "3324780",
    "zimmermann": "172418",
    "cult gaia": "425473",
    "greg lauren": "2134258",
    "bode": "531359",
    "fuzzi": "227826",
    "staud": "780806",
    "ulla johnson": "375977",
    "sea new york": "343921",
    "saloni": "503339",
    "veronica beard": "524820",
    "la doublej": "2684886",
    "self-portrait": "248126",
    "jonathan simkhai": "473679",
    "simkhai": "473679",
    "brunello cucinelli": "103740", "rick owens": "145654",
    "patagonia": "90804",
    "marni": "12251", "missoni": "4463", "jean paul gaultier": "4129",
    "jpg": "4129", "emilio pucci": "10831", "pucci": "10831",
    "issey miyake": "75090", "pleats please": "395642",
    "pleats please issey miyake": "395642", "claude montana": "121608",
    "miu miu": "1745", "thierry mugler": "284", "mugler": "284",
    "courreges": "12639", "courrèges": "12639",
    "m missoni": "1702343", "missoni home": "2776470",
    "missoni mare": "2720679", "vivienne westwood": "14217",
    "yohji yamamoto": "200474", "dries van noten": "72138",
    "ann demeulemeester": "51445", "raf simons": "184436", "loewe": "24209",
    "helmut lang": "47829",
    "bottega veneta": "86972", "maison margiela": "639289",
    "margiela": "639289", "max mara": "5483",
    "veilance": "3388210", "nanga": "434286",
    "snow peak": "666350", "acronym": "712647",
    "isabel marant": "14361",
    "alaïa": "69184",
    "alaia": "69184",
    "yves saint laurent": "377",
    "junya watanabe": "235040",
    "thom browne": "399438",
    "khaite": "806862",
    "alexander mcqueen": "52193",
    "chloé": "2113",
    "chloe": "2113",
    "stella mccartney": "13893",
    "totême": "546105",
    "toteme": "546105",
    "ermenegildo zegna": "174480",
    "zegna": "174480",
    "loro piana": "219848",
    "lemaire": "295938",
    "the frankie shop": "378382",
    "frankie shop": "378382",
    "number (n)ine": "505614",
    "number nine": "505614",
    "takahiromiyashita thesoloist": "1726469",
    "takahiromiyashita the soloist": "1726469",
    "thesoloist": "1726469",
    "the soloist": "1726469",
    "engineered garments": "609050",
    "undercover": "59974",
    "visvim": "276225",
    "45rpm": "464091",
    "kapital": "576107",
    "carol christian poell": "1996050", "ccp": "1996050",
    "haider ackermann": "232276",
    "the row": "547584",
    "boris bidjan saberi": "484649", "bbs": "484649",
    "sacai": "369700",
    "kiko kostadinov": "5821136",
    # I brand sotto sono stati aggiunti il 2026-10-01, richiesti dall'utente come nuovi
    # watch (capispalla contemporaneo + lusso "che fa rumore" con rischio fake gestibile).
    # ID presi da teddy-vltn/vinted-dataset (brand.json, dataset statico su GitHub, non una
    # richiesta a Vinted) e incrociati con 7 ID verificati in precedenza direttamente da
    # Vinted (Gucci, Burberry, Louis Vuitton, Dior, Ralph Lauren, Michael Kors, Sandro):
    # combaciavano tutti e 7, da qui la fiducia nel resto del file.
    "prada": "3573",
    "fendi": "1189",
    "jacquemus": "168278",
    "acne studios": "180798",
    "the attico": "1653053",  # id dato direttamente dall'utente il 2026-10-01
    # Secondo giro di aggiunte (2026-10-01): l'utente ha corretto le mie stime di rivendita
    # troppo prudenti su Maje/Sandro ("hanno prezzi alti su Vestiaire") e ha scelto di
    # allargare il watch invece di pre-filtrare su stime incerte -- "mettiamo tutti e
    # vediamo come va con un po' di notifiche". Stessa fonte (teddy-vltn/vinted-dataset).
    "acne studios": "180798",
    "barena venezia": "703380", "barena": "703380",
    # Comme des Garçons: unico ID di questo giro NON incrociato con uno dei 7 gia'
    # verificati direttamente da Vinted -- controllare che l'URL risultante mostri
    # davvero Comme des Garçons prima di fidarsene.
    "comme des garçons": "16352233", "comme des garcons": "16352233",
}

MATERIALI_PREGIATI_PRIORITA = [
    "cashmere", "vicuna", "vigogna", "seta", "velluto", "pelle", "shearling",
    "montone", "renna", "alpaca", "mohair", "lana", "lino", "viscosa", "lurex",
    "denim", "cotone",
]

MATERIALI_TRADUZIONI = {
    "silk": "seta", "soie": "seta", "seide": "seta",
    "velvet": "velluto", "velours": "velluto", "samt": "velluto",
    "leather": "pelle", "cuir": "pelle", "leder": "pelle",
    "wool": "lana", "laine": "lana", "wolle": "lana",
    "linen": "lino", "lin": "lino", "leinen": "lino",
    "cotton": "cotone", "coton": "cotone", "baumwolle": "cotone",
    "cashmere": "cashmere", "cachemire": "cashmere", "kaschmir": "cashmere",
    "viscose": "viscosa", "viskose": "viscosa",
    "mohair": "mohair", "alpaca": "alpaca", "alpaga": "alpaca",
}

# CATEGORIE MULTILINGUA (IT / EN / DE / FR / ES / PT) -- ampliata per coprire
# molti piu' tipi di capo e ridurre i casi di categoria non rilevata, che in
# precedenza causavano un fallback pericoloso ("dress") nella ricerca Vestiaire.
CATEGORIA_KEYWORDS = {
    "abito": ["abito", "vestito", "kleid", "dress", "robe", "vestido"],
    "blusa": ["blusa", "camicetta", "bluse", "blouse", "chemisier"],
    "camicia": ["camicia", "hemd", "shirt", "chemise", "camisa", "camisola"],
    # "cardigan" aggiunto il 2026-09-20: assente prima in ogni categoria (ne'
    # qui ne' altrove nel dizionario), quindi un titolo come "Jean Paul
    # Gaultier Blue Cardigan" non veniva classificato in NESSUNA categoria
    # (estrai_categoria_da_titolo tornava None) -- e con categoria=None
    # _filtra_comp_per_categoria e' un no-op per definizione, quindi i comp
    # visuali restavano completamente non filtrati (borse/vestiti/gonne
    # mescolati) anche dopo il fix dell'ordinamento. Osservato in log di
    # produzione reali.
    "maglia": ["maglia", "maglione", "pullover", "sweater", "pull", "jumper", "jersey", "suéter", "trui", "strick", "cardigan"],
    "t-shirt": ["t-shirt", "tshirt", "t shirt", "maglietta", "camiseta", "playera"],
    "canotta": ["canotta", "canottiera", "top", "tank top", "canotte", "débardeur", "tirantes"],
    "felpa": ["felpa", "hoodie", "sweatshirt", "sudadera", "kapuzenpulli"],
    "gonna": ["gonna", "rock", "skirt", "jupe", "falda", "saia"],
    "pantaloni": ["pantaloni", "pantalone", "hose", "trousers", "pants", "pantalon", "pantalón", "calças"],
    "jeans": ["jeans", "denim", "vaqueros", "vaquero"],
    "giacca": ["giacca", "jacke", "jacket", "veste", "chaqueta", "casaco"],
    "gilet": ["gilet", "smanicato", "weste", "vest", "waistcoat", "chaleco", "colete"],
    "cappotto": ["cappotto", "mantel", "coat", "manteau", "abrigo", "casaco longo"],
    "borsa": ["borsa", "tasche", "bag", "sac", "bolso", "bolsa"],
    "scarpe": ["scarpe", "schuhe", "shoes", "chaussures", "zapatos", "sapatos"],
    "polo": ["polo"],
    "costume": ["costume", "bikini", "swimsuit", "maillot", "bañador"],
    "intimo": ["intimo", "underwear", "lingerie", "ropa interior"],
    "sciarpa": ["sciarpa", "scarf", "echarpe", "bufanda"],
    "cintura": ["cintura", "belt", "ceinture", "cinturón"],
    "cappello": ["cappello", "hat", "chapeau", "sombrero", "cap", "berretto"],
    "occhiali": ["occhiali", "gafas", "lunettes", "glasses", "brille", "monturas", "montatura"],
    "tuta": ["tuta", "combinaison", "combishort", "jumpsuit", "playsuit", "overall", "salopette"],
}

# Termine inglese "canonico" per ogni categoria, usato per le query eBay/
# Vestiaire (dove i titoli sono in stragrande maggioranza in inglese anche
# su siti localizzati IT/DE/FR). Cercare in italiano ("canotta") su questi
# marketplace produce spesso zero match sul termine di categoria, facendo
# collassare la query a "solo brand" e restituendo risultati fuori tema.
CATEGORIA_TERMINE_EN = {
    "abito": "dress",
    "blusa": "blouse",
    "camicia": "shirt",
    "maglia": "sweater",
    "t-shirt": "t-shirt",
    "canotta": "tank top",
    "felpa": "hoodie",
    "gonna": "skirt",
    "pantaloni": "trousers",
    "jeans": "jeans",
    "giacca": "jacket",
    "gilet": "vest",
    "cappotto": "coat",
    "borsa": "bag",
    "scarpe": "shoes",
    "polo": "polo",
    "costume": "swimsuit",
    "intimo": "underwear",
    "sciarpa": "scarf",
    "cintura": "belt",
    "cappello": "hat",
    "occhiali": "glasses",
    "tuta": "jumpsuit",
}


VINTED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
IMAGE_DOWNLOAD_HEADERS = {
    "User-Agent": VINTED_HEADERS["User-Agent"],
    "Accept-Language": VINTED_HEADERS["Accept-Language"],
    "Referer": "https://www.vinted.it/",
    "Accept": "image/webp,image/avif,image/jpeg,image/png,image/*,*/*;q=0.8",
    "Sec-Fetch-Dest": "image", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "same-site",
    "Connection": "keep-alive",
}
