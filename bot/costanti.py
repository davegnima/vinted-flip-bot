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
