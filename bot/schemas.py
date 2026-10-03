"""Modulo estratto da main_telethon.py (spostamento meccanico)."""


from bot.costanti import CATEGORIA_TERMINE_EN
# ---- fine import ----
OCCHIO_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "propertyOrdering": [
        # 1. EVIDENZA: cosa posso davvero vedere
        "qualita_evidenza",
        "segnali_rischio_annuncio",

        # 2. TRASCRIZIONE VERBATIM: prima di interpretare
        "etichette",
        "brand_letto_etichetta",
        "composizione_da_etichetta",
        "taglia_etichetta",

        # 3. IDENTIFICAZIONE: cosa deduco dalle trascrizioni
        "relazione_brand",
        "nome_sottolinea",
        "sottolinea_max_mara_eccezione",
        "categoria_capo_osservata",
        "linea_o_era",
        "evidenze_datazione",
        "modello_riconosciuto",
        "dettaglio_distintivo_ricerca",

        # 4. OSSERVAZIONE FISICA
        "materiale_osservato_dalle_foto",
        "coerenza_materiale",
        "indicatori_costruzione",
        "livello_fattura",
        "hardware_dettaglio",
        "condizione_osservata",
        "difetti",

        # 5. CONTROPROVE: prima del verdetto, non dopo
        "riscontri_autenticita",
        "controprova_prezzo_eseguita",

        # 6. VERDETTO: solo ora
        "verdetto_legit",
        "confidenza_legit",
        "motivo_sintetico",
        "foto_mancanti_richieste",

        # 7. VENDITORE E SINTESI
        "profilo_venditore",
        "evidenza_profilo",
        "sintesi_visiva",
    ],
    "properties": {

        # =================================================================
        # 1. EVIDENZA
        # =================================================================
        "qualita_evidenza": {
            "type": "STRING",
            "format": "enum",
            "enum": ["sufficiente_per_verdetto", "parziale_servono_altre_foto", "insufficiente"],
            "description": (
                "Quanto le foto permettono un giudizio. Dichiaralo PRIMA di qualsiasi "
                "verdetto: un verdetto netto su evidenza insufficiente e' un errore."
            ),
        },
        "segnali_rischio_annuncio": {
            "type": "ARRAY",
            "maxItems": 4,
            "items": {
                "type": "STRING",
                "format": "enum",
                "enum": [
                    "foto_stock_non_del_capo", "screenshot_di_altro_annuncio",
                    "watermark_di_altro_sito", "capi_diversi_tra_le_foto",
                    "foto_di_uno_schermo", "descrizione_incoerente_con_le_foto",
                ],
            },
            "description": (
                "Frode che riguarda l'ANNUNCIO, non il capo. Vuoto se nessuno. "
                "'capi_diversi_tra_le_foto': usalo SOLO se piu' foto mostrano chiaramente "
                "capi d'abbigliamento diversi tra loro (es. una giacca in una foto, un vestito "
                "in un'altra). Se una delle foto ricevute NON mostra affatto un capo "
                "d'abbigliamento ma una persona, un veicolo, un paesaggio o altro soggetto "
                "estraneo, e' quasi certamente la foto profilo del venditore finita per errore "
                "nel lotto (capita, e' un bug noto dello scraping, non un segnale di frode): "
                "ignora quella foto specifica per questo controllo, non usarla come prova di "
                "'capi diversi'."
            ),
        },

        # =================================================================
        # 2. TRASCRIZIONE VERBATIM
        # =================================================================
        "etichette": {
            "type": "ARRAY",
            "maxItems": 8,
            "description": "Una voce per ogni etichetta visibile, anche parziale. Vuoto se nessuna.",
            "items": {
                "type": "OBJECT",
                "propertyOrdering": ["tipo", "testo_verbatim", "leggibilita", "osservazioni_tecniche"],
                "properties": {
                    "tipo": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": [
                            "main_label", "wash_care_tag", "etichetta_taglia",
                            "etichetta_composizione", "codice_prodotto",
                            "etichetta_storica_o_union", "ologramma_autenticita",
                            "etichetta_rivenditore", "altro",
                        ],
                    },
                    "testo_verbatim": {
                        "type": "STRING",
                        "description": (
                            "Testo ESATTO, carattere per carattere, comprese maiuscole, "
                            "apostrofi e simboli. Usa [...] per le parti illeggibili. E' la "
                            "prova su cui si reggono tutte le deduzioni successive."
                        ),
                    },
                    "leggibilita": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["nitida", "parziale", "illeggibile"],
                    },
                    "osservazioni_tecniche": {
                        "type": "STRING",
                        "nullable": True,
                        "description": (
                            "L'etichetta come OGGETTO FISICO: tessuta o stampata, font, "
                            "densita' del ricamo, come e' cucita, materiale del nastro, "
                            "invecchiamento coerente col capo."
                        ),
                    },
                },
                "required": ["tipo", "testo_verbatim", "leggibilita"],
            },
        },
        "brand_letto_etichetta": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Il brand ESATTAMENTE come letto, senza correggerlo: se l'etichetta dice "
                "'Kapitales' scrivi 'Kapitales', non 'Kapital'."
            ),
        },
        "composizione_da_etichetta": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Composizione verbatim con le percentuali (es. '100% CASHMERE'). Solo da "
                "etichetta fisica: NON dedurla dal titolo dell'annuncio."
            ),
        },
        "taglia_etichetta": {
            "type": "STRING",
            "nullable": True,
            "description": "Taglia come stampata sull'etichetta (es. 'IT 48', 'M', 'US 10').",
        },

        # =================================================================
        # 3. IDENTIFICAZIONE
        # =================================================================
        "relazione_brand": {
            "type": "STRING",
            "format": "enum",
            "enum": [
                "corrisponde", "sottolinea_stessa_maison", "brand_estraneo",
                "tessuto_non_brand", "non_leggibile",
            ],
            "description": (
                "'sottolinea_stessa_maison' = MM6 per Margiela, See by Chloe per Chloe, "
                "Weekend per Max Mara: ha ancora valore. 'brand_estraneo' = marchio diverso e "
                "NON correlato (es. 'Kapitales' per 'Kapital'): il sistema scarta l'annuncio "
                "senza altre verifiche, quindi usalo solo se sei sicuro. 'tessuto_non_brand' = "
                "il nome letto (es. Loro Piana, Zegna, Vitale Barberis Canonico) e' SOLO il "
                "fornitore del tessuto usato per il capo, non il produttore del capo finito -- "
                "vedi istruzioni dettagliate nel prompt. Nel dubbio tra 'corrisponde' e "
                "'tessuto_non_brand', usa 'tessuto_non_brand'. 'non_leggibile' solo se non leggi "
                "NESSUN nome, ne' di brand ne' di tessuto."
            ),
        },
        "nome_sottolinea": {
            "type": "STRING",
            "nullable": True,
            "description": "Nome della sottolinea se applicabile (es. 'MM6', 'McQ', 'M Missoni', 'Weekend Max Mara').",
        },
        "sottolinea_max_mara_eccezione": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Compila SOLO quando nome_sottolinea e' una sottolinea Max Mara "
                "non-mainline (Weekend, Studio, Sportmax, Marella, Pennyblack, "
                "Max&Co): a differenza delle altre sottolinee (MM6, See by Chloe...), "
                "che il Cervello valuta sempre normalmente, per queste il sistema "
                "scarta l'annuncio PRIMA del Cervello a meno che tu non descriva qui "
                "una ragione CONCRETA per cui questo esemplare specifico fa "
                "eccezione: un modello iconico riconosciuto (coerente con "
                "modello_riconosciuto) oppure un materiale pregiato dichiarato "
                "ESPLICITAMENTE sull'etichetta di composizione (cashmere, pelle, "
                "seta, lana vergine pregiata -- non basta 'lana' generica). null se "
                "nessuna delle due condizioni ha evidenza concreta nelle foto: in "
                "quel caso l'annuncio viene scartato senza consultare il Cervello, "
                "perche' senza eccezione la sottolinea vale troppo poco per "
                "giustificare la ricerca comp. Non compilare per nessun altro brand "
                "o sottolinea."
            ),
        },
        "categoria_capo_osservata": {
            "type": "STRING",
            "description": (
                "Categoria come si VEDE nelle foto, non come la chiama il titolo "
                "(es. 'giubbotto di jeans'): serve a intercettare i titoli fuorvianti."
            ),
        },
        "linea_o_era": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Linea o era desunta dalle etichette (es. 'Era Lang 1986-2005', 'Era Link "
                "Theory post-2006', 'Linea 10', 'mainline'). null se le etichette non lo "
                "permettono: da qui dipende il valore stimato."
            ),
        },
        "evidenze_datazione": {
            "type": "ARRAY",
            "maxItems": 5,
            "items": {"type": "STRING"},
            "description": (
                "I segnali concreti su cui si basa linea_o_era: formato del wash tag, paese "
                "di produzione, stile del logo, formato del codice, diciture legate a "
                "un'epoca. Un'era senza evidenze elencate qui vale come non dichiarata."
            ),
        },
        "modello_riconosciuto": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Nome del modello se riconoscibile come pezzo d'archivio noto. null se non "
                "lo riconosci con certezza: non tirare a indovinare un nome iconico."
            ),
        },
        "dettaglio_distintivo_ricerca": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Un dettaglio di taglio o design che distingue questo capo da un capo "
                "generico dello stesso brand+categoria (es. 'ruffle sleeve', 'asymmetric "
                "hem', 'puff sleeve', 'cropped fit', 'peplum waist'), in 2-4 parole "
                "INGLESI pronte per una query di ricerca su marketplace americani (eBay, "
                "Poshmark) -- non in italiano, non una frase completa. null se il capo non "
                "ha un dettaglio chiaramente distintivo da segnalare: non inventarne uno "
                "per riempire il campo, un taglio generico (es. un maglione girocollo "
                "senza altro) resta null."
            ),
        },

        # =================================================================
        # 4. OSSERVAZIONE FISICA
        # =================================================================
        "materiale_osservato_dalle_foto": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Che materiale SEMBRA da drappeggio, riflesso, grana, peluria, pieghe. "
                "Indipendente dall'etichetta: serve proprio a confrontarli."
            ),
        },
        "coerenza_materiale": {
            "type": "STRING",
            "format": "enum",
            "enum": ["coerente", "incoerente", "non_valutabile"],
            "description": (
                "Confronto tra composizione_da_etichetta e materiale osservato. 'incoerente' "
                "= l'aspetto smentisce l'etichetta (possibile etichetta riportata)."
            ),
        },
        "indicatori_costruzione": {
            "type": "ARRAY",
            "maxItems": 6,
            "items": {"type": "STRING"},
            "description": (
                "Dettagli di fattura osservabili: finitura delle cuciture, tipo di fodera, "
                "corrispondenza del disegno alle giunture, asole lavorate, finiture a mano, "
                "interno pulito o grezzo, peso e marchiatura di zip e bottoni. Sono cio' che "
                "distingue la qualita' vera a prescindere dall'etichetta."
            ),
        },
        "livello_fattura": {
            "type": "STRING",
            "format": "enum",
            "enum": ["alta_sartoriale", "buona_industriale", "media", "scadente", "non_valutabile"],
        },
        "hardware_dettaglio": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Marchio e aspetto di zip/bottoni/fibbie se leggibili (es. 'zip Lampo', "
                "'bottoni marchiati HELMUT LANG N.Y.'): insieme indizio di autenticita' e di "
                "datazione."
            ),
        },
        "condizione_osservata": {
            "type": "STRING",
            "format": "enum",
            "enum": ["come_nuovo", "ottime", "buone", "usato_evidente", "danneggiato"],
            "description": "La condizione che vedi TU, non quella dichiarata dal venditore.",
        },
        "difetti": {
            "type": "ARRAY",
            "maxItems": 8,
            "description": (
                "Un oggetto per ogni difetto, sia visto in foto sia dichiarato nel testo. "
                "Vuoto se non ce ne sono. Non accorpare piu' difetti in una voce."
            ),
            "items": {
                "type": "OBJECT",
                "propertyOrdering": ["tipo", "posizione", "gravita", "strutturale", "fonte"],
                "properties": {
                    "tipo": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": [
                            "macchia", "alone", "buco", "foro_da_spilla", "strappo",
                            "scucitura", "usura_tessuto", "pilling", "scolorimento",
                            "filo_tirato", "zip_difettosa", "bottoni_mancanti",
                            "rammendo_o_riparazione", "alterazione_sartoriale",
                            "deformazione", "odore_dichiarato", "altro",
                        ],
                    },
                    "posizione": {
                        "type": "STRING",
                        "description": "Dove si trova (es. 'manica sinistra vicino al polsino').",
                    },
                    "gravita": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["lieve", "moderata", "grave"],
                    },
                    "strutturale": {
                        "type": "BOOLEAN",
                        "description": (
                            "true se compromette uso o rivendibilita' (strappo, buco aperto, "
                            "zip rotta). false per difetti estetici recuperabili."
                        ),
                    },
                    "fonte": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["visibile_in_foto", "dichiarato_dal_venditore", "entrambi"],
                        "description": (
                            "Distingue cio' che hai VISTO da cio' che ti e' stato DETTO: un "
                            "difetto solo visibile e non dichiarato e' anche un segnale sul "
                            "venditore."
                        ),
                    },
                },
                "required": ["tipo", "posizione", "gravita", "strutturale", "fonte"],
            },
        },

        # =================================================================
        # 5. CONTROPROVE
        # =================================================================
        "riscontri_autenticita": {
            "type": "ARRAY",
            "maxItems": 8,
            "description": (
                "Un oggetto per ogni elemento esaminato. E' la BASE del verdetto: il "
                "verdetto discende da qui, non precede. Elenca anche i riscontri COERENTI: "
                "un giudizio negativo su un solo elemento incoerente, ignorandone cinque "
                "coerenti, e' un errore di metodo."
            ),
            "items": {
                "type": "OBJECT",
                "propertyOrdering": ["elemento", "osservazione", "esito", "peso"],
                "properties": {
                    "elemento": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": [
                            "font_etichetta", "tessitura_etichetta", "cucitura_etichetta",
                            "wash_tag", "codice_prodotto", "paese_produzione",
                            "simboli_lavaggio", "hardware", "ricamo_logo",
                            "proporzioni_logo", "qualita_cuciture", "fodera",
                            "asole_e_bottoni", "coerenza_invecchiamento", "altro",
                        ],
                    },
                    "osservazione": {
                        "type": "STRING",
                        "description": (
                            "COSA hai visto, verificabile da chi guarda la stessa foto. "
                            "Vietato 'font grossolano' o 'sembra di bassa qualita'': specifica "
                            "in cosa differisce (spessore delle aste, spaziatura, grazie, "
                            "allineamento, densita' del punto). Se non sai dirlo con "
                            "precisione, l'esito e' 'non_valutabile'."
                        ),
                    },
                    "esito": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["coerente", "incoerente", "non_valutabile"],
                    },
                    "peso": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["forte", "medio", "debole"],
                        "description": (
                            "Quanto sposta il giudizio: un codice wash tag incoerente pesa "
                            "'forte', una cucitura irregolare su un vintage pesa 'debole'."
                        ),
                    },
                },
                "required": ["elemento", "osservazione", "esito", "peso"],
            },
        },
        "controprova_prezzo_eseguita": {
            "type": "BOOLEAN",
            "description": (
                "CONTROLLO ANTI-BIAS. Prima di dichiarare falso: con gli stessi identici "
                "dettagli, lo giudicheresti sospetto anche se il prezzo fosse dieci volte "
                "tanto? true solo se hai fatto la verifica e il giudizio regge. Se la "
                "risposta e' 'forse no', declassa a 'sospetto_servono_altre_foto'."
            ),
        },

        # =================================================================
        # 6. VERDETTO
        # =================================================================
        "verdetto_legit": {
            "type": "STRING",
            "format": "enum",
            "enum": [
                "probabilmente_autentico", "sospetto_servono_altre_foto",
                "probabilmente_falso", "non_verificabile",
            ],
            "description": (
                "Discende da riscontri_autenticita. 'probabilmente_falso' richiede almeno un "
                "riscontro 'incoerente' di peso 'forte' descritto in concreto."
            ),
        },
        "confidenza_legit": {
            "type": "STRING",
            "format": "enum",
            "enum": ["alta", "media", "bassa"],
            "description": (
                "'alta' solo con evidenza nitida e piu' riscontri concordi: falso + alta fa "
                "scartare l'annuncio senza altri controlli."
            ),
        },
        "motivo_sintetico": {
            "type": "STRING",
            "description": (
                "Una riga che nomina l'elemento decisivo e cosa hai visto. Arriva all'utente "
                "cosi' com'e' anche quando il resto della pipeline viene saltato."
            ),
        },
        "foto_mancanti_richieste": {
            "type": "ARRAY",
            "maxItems": 3,
            "items": {"type": "STRING"},
            "description": (
                "Quali foto scioglierebbero il dubbio (es. 'main label al collo in primo "
                "piano'). Obbligatorio se il verdetto e' 'sospetto_servono_altre_foto'."
            ),
        },

        # =================================================================
        # 7. VENDITORE E SINTESI
        # =================================================================
        "profilo_venditore": {
            "type": "STRING",
            "format": "enum",
            "enum": ["privato_genuino", "reseller_esperto", "non_determinabile"],
            "description": (
                "Il numero di recensioni da solo NON decide: conta COSA vende. Guardaroba "
                "misto con fast fashion accanto al lusso = privato genuino anche con "
                "centinaia di recensioni. Solo brand designer = reseller esperto."
            ),
        },
        "evidenza_profilo": {
            "type": "STRING",
            "description": (
                "Deve citare il contenuto di 'Primi articoli in vendita' quando presente, "
                "non il solo numero di recensioni."
            ),
        },
        "sintesi_visiva": {
            "type": "STRING",
            "description": (
                "3-4 righe per l'utente: cosa vedi, cosa dicono le etichette, in che "
                "condizione e'. Nessun numero finanziario, nessuna decisione d'acquisto."
            ),
        },
    },
    "required": [
        "qualita_evidenza", "segnali_rischio_annuncio",
        "etichette",
        "relazione_brand", "categoria_capo_osservata", "evidenze_datazione",
        "coerenza_materiale", "indicatori_costruzione", "livello_fattura",
        "condizione_osservata", "difetti",
        "riscontri_autenticita", "controprova_prezzo_eseguita",
        "verdetto_legit", "confidenza_legit", "motivo_sintetico",
        "foto_mancanti_richieste",
        "profilo_venditore", "evidenza_profilo", "sintesi_visiva",
    ],
}

def _rimuovi_maxitems_da_array_di_oggetti(schema):
    """Deriva lo schema da spedire davvero a Gemini togliendo maxItems SOLO
    dagli array il cui items e' di tipo OBJECT.

    Workaround per il complexity budget di Gemini (vedi commento sopra
    OCCHIO_RESPONSE_SCHEMA): confermato via GitHub issue vercel/ai#21192,
    che riporta lo stesso identico 400 generico risolto rimuovendo maxItems
    dagli array di oggetti mantenendo pero' la validazione (e quindi il
    limite) lato codice. maxItems sugli array di stringhe/numeri resta,
    perche' e' quello a basso costo e non e' la causa del problema.

    Ricorsiva e non distruttiva: ritorna un nuovo dict, OCCHIO_RESPONSE_SCHEMA
    resta intatto come fonte di verita' per i test e per il troncamento
    locale in valida_payload_occhio.
    """
    if not isinstance(schema, dict):
        return schema

    convertito = dict(schema)

    if "properties" in convertito:
        convertito["properties"] = {
            nome: _rimuovi_maxitems_da_array_di_oggetti(sotto)
            for nome, sotto in convertito["properties"].items()
        }

    if "items" in convertito:
        convertito["items"] = _rimuovi_maxitems_da_array_di_oggetti(convertito["items"])

    if (
        convertito.get("type") == "ARRAY"
        and isinstance(convertito.get("items"), dict)
        and convertito["items"].get("type") == "OBJECT"
        and "maxItems" in convertito
    ):
        convertito = {k: v for k, v in convertito.items() if k != "maxItems"}

    return convertito

# Schema REALMENTE spedito a Gemini: senza maxItems sugli array di oggetti,
# per non sforare il complexity budget descritto sopra. Il limite di 8 voci
# per etichette/difetti/riscontri_autenticita resta comunque garantito, ma
# applicato in Python (valida_payload_occhio) invece che dallo schema.
OCCHIO_RESPONSE_SCHEMA_GEMINI = _rimuovi_maxitems_da_array_di_oggetti(OCCHIO_RESPONSE_SCHEMA)

CATEGORIE_CAPO_ENUM = sorted(CATEGORIA_TERMINE_EN.keys()) + ["non_determinabile"]

CERVELLO_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "propertyOrdering": [
        "brand_dichiarato_annuncio",
        "brand_reale_etichetta",
        "corrispondenza_brand",
        "linea_o_era_rilevata",
        "tetto_prezzo_linea_eur",
        "categoria_capo",
        "materiale_rilevato",
        "materiale_confermato",
        "taglia_rilevata",
        "fascia_taglia",
        "comp_candidati",
        "comp_riferimento_eur",
        "sconto_ask_applicato_pct",
        "prezzo_target_vendita_eur",
        "difetto_significativo",
        "difetto_strutturale",
        "gravita_difetto_strutturale",
        "sconto_difetto_pct",
        "descrizione_difetto",
        "giorni_stimati_vendita",
        "mese_consigliato_pubblicazione",
        "legit_verdetto",
        "legit_motivo_specifico",
        "rischio_fake",
        "confidenza",
        "profilo_venditore",
        "motivo_profilo_venditore",
        "domanda_mercato",
        "segnali_domanda",
        "deal_score",
        "note_analista",
        "domande_al_venditore",
        "messaggio_venditore_template",
    ],
    "properties": {
        # --- 1. ANCORAGGIO AL BRAND: il modello si impegna PRIMA di vedere numeri
        "brand_dichiarato_annuncio": {
            "type": "STRING",
            "description": "Brand come dichiarato nell'annuncio Vinted.",
        },
        "brand_reale_etichetta": {
            "type": "STRING",
            "nullable": True,
            "description": "Testo ESATTO letto sull'etichetta dall'analisi visiva. null se nessuna etichetta leggibile.",
        },
        "corrispondenza_brand": {
            "type": "STRING",
            "format": "enum",
            "enum": ["corrisponde", "sottolinea_stessa_maison", "brand_estraneo", "non_verificabile"],
            "description": (
                "'sottolinea_stessa_maison' = MM6 per Margiela, See by Chloe per Chloe, "
                "Weekend per Max Mara: ha ancora valore, si valuta normalmente. "
                "'brand_estraneo' = marchio diverso e non correlato (es. Kapitales invece "
                "di Kapital): verdetto gia' scontato, nessun comp necessario."
            ),
        },
        "linea_o_era_rilevata": {
            "type": "STRING",
            "description": (
                "Linea o era precisa secondo la tabella LINEE E ERE. Esempi validi: "
                "'Era Lang 1986-2005', 'Era Link Theory post-2006', 'Linea 10', 'MM6', "
                "\"JEAN'S PAUL GAULTIER\", \"JPG.JEAN'S\", 'Veilance', 'mainline', "
                "'non determinabile'."
            ),
        },
        "tetto_prezzo_linea_eur": {
            "type": "NUMBER",
            "nullable": True,
            "description": (
                "Tetto di rivendita imposto dalla linea quando la tabella ne prevede uno "
                "(es. 30 per JEAN'S PAUL GAULTIER). null se nessun tetto si applica."
            ),
        },

        # --- 2. IDENTITA' DEL CAPO
        "categoria_capo": {
            "type": "STRING",
            "format": "enum",
            "enum": CATEGORIE_CAPO_ENUM,
        },
        "materiale_rilevato": {"type": "STRING", "nullable": True},
        "materiale_confermato": {
            "type": "BOOLEAN",
            "description": (
                "true se il materiale compare ESPLICITAMENTE nel titolo, nella descrizione, "
                "nei dati strutturati dell'annuncio, o e' leggibile su etichetta -- non serve "
                "una foto ravvicinata della sola etichetta di composizione (es. titolo "
                "'Kaschmir Pullover' = true). false SOLO se il materiale non e' menzionato da "
                "nessuna parte e andrebbe indovinato dalla sola foto generica: in quel caso il "
                "sistema abbassa la stima al 75* percentile dei comp validi invece che al piu' caro."
            ),
        },
        "taglia_rilevata": {"type": "STRING", "nullable": True},
        "fascia_taglia": {
            "type": "STRING",
            "format": "enum",
            "enum": ["centrale", "estrema", "ignota"],
            "description": (
                "centrale = donna IT 40-44 / uomo IT 48-52 (bacino ampio). "
                "estrema = fuori da quelle fasce: riduce liquidita' e domanda."
            ),
        },

        # --- 3. COMP: prezzi verbatim, un oggetto per comp, niente prosa
        "comp_candidati": {
            "type": "ARRAY",
            "minItems": 0,
            "description": (
                "OGNI prezzo comp valutato, anche quelli scartati. I prezzi presi dai dati "
                "ricevuti vanno copiati alla lettera; quelli che vengono dalla tua "
                "conoscenza del brand vanno marcati fonte='memoria_modello'."
            ),
            "items": {
                "type": "OBJECT",
                "propertyOrdering": [
                    "titolo_verbatim", "prezzo_eur", "fonte",
                    "stessa_categoria", "stessa_linea", "corrispondenza_materiale",
                    "escluso", "motivo_esclusione",
                ],
                "properties": {
                    "titolo_verbatim": {
                        "type": "STRING",
                        "description": "Titolo del comp copiato alla lettera dai dati ricevuti.",
                    },
                    "prezzo_eur": {
                        "type": "NUMBER",
                        "description": "Prezzo in euro. Se viene dai dati ricevuti, copiato alla lettera, mai arrotondato.",
                    },
                    "fonte": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["vinted_testo", "vinted_visuale", "ebay_poshmark", "memoria_modello"],
                        "description": (
                            "'ebay_poshmark' = comp dai dati eBay/Poshmark pre-raccolti (via Resellbot). "
                            "'memoria_modello' = prezzo che ricordi tu, non presente nei dati "
                            "ricevuti in questa conversazione. Dichiararlo e' obbligatorio e non "
                            "comporta alcuna penalizzazione."
                        ),
                    },
                    "stessa_categoria": {"type": "BOOLEAN"},
                    "stessa_linea": {
                        "type": "BOOLEAN",
                        "description": "false per Y-3 su Yohji, McQ su McQueen, See by Chloe su Chloe, MM6 su Margiela mainline.",
                    },
                    "corrispondenza_materiale": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["stesso", "diverso", "ignoto"],
                    },
                    "escluso": {"type": "BOOLEAN"},
                    "motivo_esclusione": {"type": "STRING", "nullable": True},
                },
                "required": [
                    "titolo_verbatim", "prezzo_eur", "fonte",
                    "stessa_categoria", "stessa_linea", "corrispondenza_materiale", "escluso",
                ],
            },
        },
        "comp_riferimento_eur": {
            "type": "NUMBER",
            "nullable": True,
            "description": (
                "Il prezzo, tra i comp NON esclusi, su cui ancori la stima. Deve essere uno "
                "dei prezzo_eur dichiarati sopra. null se non c'e' nessun comp valido."
            ),
        },
        "sconto_ask_applicato_pct": {
            "type": "INTEGER",
            "description": "Sconto prudenziale applicato al comp ASK di riferimento, tra 20 e 30.",
        },

        # --- 4. L'UNICO NUMERO ECONOMICO CHE IL MODELLO PRODUCE
        "prezzo_target_vendita_eur": {
            "type": "NUMBER",
            "description": (
                "Prezzo LORDO di listing previsto. NON calcolare margine, ROI, incasso o "
                "costo d'acquisto: li calcola il sistema. Non puo' superare il comp di "
                "riferimento gia' scontato, ne' tetto_prezzo_linea_eur."
            ),
        },
        # --- difetto del capo (NON il materiale, NON lo sconto ASK dei comp):
        # riguarda SOLO le condizioni di QUESTO esemplare specifico. Il
        # sistema applica sconto_difetto_pct come ulteriore riduzione
        # moltiplicativa sul prezzo target, DOPO tutti gli altri limiti --
        # prima non esisteva nessun controllo numerico su questo, un difetto
        # descritto in note_analista poteva non riflettersi affatto nel
        # prezzo finale se il cervello si "dimenticava" di scontarlo da solo.
        "difetto_significativo": {
            "type": "BOOLEAN",
            "description": (
                "true se il capo ha un difetto che un compratore noterebbe e che ne riduce "
                "il valore (macchia, buco, filo tirato, cerniera/bottone rotto, alterazione, "
                "usura marcata, foro di spilla, scolorimento, ecc.). false per normale segno "
                "d'uso di un capo second-hand descritto come 'ottime condizioni' senza difetti "
                "specifici citati."
            ),
        },
        "difetto_strutturale": {
            "type": "BOOLEAN",
            "description": (
                "true se ALMENO UNO dei difetti compromette l'uso o la rivendibilita' del "
                "capo: buco aperto, strappo, tessuto lacerato, cuciture saltate su una "
                "giuntura portante, cerniera rotta non sostituibile, muffa. false per difetti "
                "estetici recuperabili (pilling, macchia lavabile, filo tirato, foro di "
                "spilla, bottone mancante sostituibile). Non decide da solo il blocco: e' "
                "`gravita_difetto_strutturale` che stabilisce se il capo resta vendibile a "
                "forte sconto o se e' invendibile -- vedi sotto."
            ),
        },
        "gravita_difetto_strutturale": {
            "type": "STRING",
            "format": "enum",
            "enum": ["lieve", "moderata", "grave"],
            "nullable": True,
            "description": (
                "Obbligatorio (non null) se difetto_strutturale=true, altrimenti null. Caso "
                "reale che ha corretto questa regola: una t-shirt Jean Paul Gaultier d'archivio "
                "con un piccolo foro isolato sulla manica in tessuto a rete -- il sistema la "
                "scartava sempre come invendibile, ma un difetto cosi' piccolo e localizzato su "
                "un pezzo d'archivio resta perfettamente vendibile a sconto, dichiarato in "
                "descrizione. 'lieve' = difetto strutturale ma PICCOLO e LOCALIZZATO (un foro "
                "isolato, pochi cm di cucitura saltata su una giuntura secondaria): il capo "
                "resta vendibile a forte sconto, NON viene bloccato automaticamente. "
                "'moderata' = piu' esteso o su una giuntura piu' portante, ma il capo e' ancora "
                "indossabile e vendibile dichiarandolo: non bloccato, ma il prezzo deve "
                "riflettere il rischio (sconto_difetto_pct alto, verso il 50%). 'grave' = il "
                "capo e' sostanzialmente invendibile: piu' difetti strutturali combinati, area "
                "ampia compromessa, cerniera principale inutilizzabile, capo che rischia di "
                "peggiorare con il solo indossarlo. SOLO 'grave' fa scattare il blocco "
                "automatico a NON COMPRARE; 'lieve' e 'moderata' restano un capo normalmente "
                "valutabile, scontato tramite sconto_difetto_pct come ogni altro difetto. Nel "
                "dubbio tra 'moderata' e 'grave', scegli 'grave': e' la scelta prudente."
            ),
        },
        "sconto_difetto_pct": {
            "type": "NUMBER",
            "nullable": True,
            "description": (
                "Percentuale di sconto (0-50) da applicare al prezzo target per via del "
                "difetto, proporzionata alla gravita': difetto lieve/quasi invisibile ~5-10%, "
                "difetto visibile ma non strutturale (piccolo foro, filo tirato, macchia "
                "leggera) ~15-25%, difetto strutturale o che compromette l'uso (strappo, "
                "cerniera rotta, macchia estesa) ~30-50%. Pesa anche POSIZIONE e VISIBILITA', "
                "non solo dimensione: lo stesso foro conta meno se e' sotto l'ascella, sul "
                "retro o in un punto normalmente coperto, conta di piu' se e' sul petto, su una "
                "manica in vista o su un bordo. Non serve (e non va fatto) un trattamento "
                "diverso per marchio o rarita' del capo: quello e' gia' incorporato nel prezzo "
                "dei comp che stai scontando, un secondo aggiustamento lo conterebbe due volte. "
                "0 o null se difetto_significativo "
                "e' false. Decidilo tu in base a quanto descritto/visto, il sistema si limita "
                "ad applicarlo: non scontarlo gia' tu dentro prezzo_target_vendita_eur, "
                "altrimenti verrebbe scontato due volte."
            ),
        },
        "descrizione_difetto": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Cosa e' il difetto, in poche parole (es. 'piccolo foro da spilla sulla manica "
                "sinistra'). null se difetto_significativo e' false."
            ),
        },

        "giorni_stimati_vendita": {"type": "INTEGER"},
        "mese_consigliato_pubblicazione": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Solo se il capo e' fuori stagione (capispalla invernali da settembre, "
                "capi estivi da aprile). La stagionalita' allunga i tempi, non abbassa il prezzo."
            ),
        },

        # --- 5. LEGIT E RISCHIO
        "legit_verdetto": {
            "type": "STRING",
            "format": "enum",
            "enum": [
                "probabilmente_autentico",
                "sospetto_servono_altre_foto",
                "probabilmente_falso",
                "non_verificabile",
            ],
        },
        "legit_motivo_specifico": {
            "type": "STRING",
            "description": (
                "Discrepanza concreta: font dell'etichetta e in cosa differisce, proporzioni "
                "del logo, cuciture, materiale, wash tag incoerente, hardware. Vietate le "
                "formule generiche ('font grossolano', 'dettagli generici'). Obbligatorio e "
                "circostanziato quando il verdetto e' probabilmente_falso."
            ),
        },
        "rischio_fake": {
            "type": "STRING", "format": "enum",
            "enum": ["basso", "medio", "alto", "molto_alto"],
        },
        "confidenza": {
            "type": "STRING", "format": "enum",
            "enum": ["alta", "media", "bassa"],
        },

        # --- 6. VENDITORE E DOMANDA (input dell'urgenza, calcolata in Python)
        "profilo_venditore": {
            "type": "STRING", "format": "enum",
            "enum": ["privato_genuino", "reseller_esperto", "non_determinabile"],
        },
        "motivo_profilo_venditore": {
            "type": "STRING",
            "description": (
                "Deve citare esplicitamente il contenuto di 'Primi articoli in vendita' "
                "quando presente nei dati, non il solo numero di recensioni."
            ),
        },
        "domanda_mercato": {
            "type": "STRING", "format": "enum",
            "enum": ["alta", "media", "bassa"],
            "description": (
                "Domanda per QUESTO modello a QUESTA taglia, indipendente da margine e ROI. "
                "'alta' richiede segnali concreti elencati in segnali_domanda."
            ),
        },
        "segnali_domanda": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "Segnali concreti e verificabili. Array vuoto se non ce ne sono.",
        },
        "deal_score": {"type": "INTEGER", "description": "Qualita' dell'affare da 1 a 10: quanto il prezzo d'acquisto e' sotto il valore di rivendita che stimi, pesato per autenticita' e liquidita' (1-3 pessimo o rischioso, 4-6 normale, 7-10 vero affare). Spiegalo in note_analista."},

        # --- 7. TESTO PER TELEGRAM (nessun numero finanziario qui dentro)
        "note_analista": {
            "type": "STRING",
            "description": (
                "Max 6 frasi brevi, solo fatti dall'annuncio e dalle foto: cos'e' il capo (tipo, materiale, taglia, stato); "
                "perche' e' autentico o sospetto (cosa hai visto); su quali comp si basa il prezzo di rivendita e "
                "perche' proprio quello; perche' quel deal_score; dove lo vendi (Vinted, Vestiaire, eBay...) e se "
                "servono riparazioni, lavaggio o stiro. "
                "Non scrivere margine, ROI, decisione, giorni di vendita: li inserisce il sistema."
            ),
        },
        "domande_al_venditore": {
            "type": "ARRAY",
            "maxItems": 2,
            "items": {"type": "STRING"},
            "description": (
                "Array vuoto se non servono davvero per legit-check, difetti o trattativa. "
                "Non riempirlo per curiosita'."
            ),
        },
        "messaggio_venditore_template": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Messaggio pronto per il venditore. Se serve indicare un'offerta scrivi "
                "ESATTAMENTE il segnaposto {OFFERTA}: l'importo lo calcola e lo sostituisce "
                "il sistema. Non scrivere mai una cifra in euro qui dentro. null se non serve "
                "nessun messaggio."
            ),
        },
    },
    "required": [
        "brand_dichiarato_annuncio", "corrispondenza_brand", "linea_o_era_rilevata",
        "categoria_capo", "materiale_confermato", "fascia_taglia",
        "comp_candidati", "sconto_ask_applicato_pct", "prezzo_target_vendita_eur",
        "difetto_significativo", "difetto_strutturale", "gravita_difetto_strutturale",
        "giorni_stimati_vendita", "legit_verdetto", "legit_motivo_specifico",
        "rischio_fake", "confidenza", "profilo_venditore", "motivo_profilo_venditore",
        "domanda_mercato", "segnali_domanda", "deal_score", "note_analista",
        "domande_al_venditore",
    ],
}

def _schema_gemini_to_openai(schema):
    """Converte lo schema Gemini (dialetto OpenAPI, tipi MAIUSCOLI, nullable
    booleano, propertyOrdering) nel JSON Schema che OpenAI accetta in
    response_format.json_schema con strict=true.

    Esiste per avere UNA sola fonte di verita': lo schema si scrive una
    volta sopra, e il ramo OpenAI (CERVELLO_PROVIDER=openai) ne riceve
    automaticamente la traduzione. Senza questa funzione i due schemi
    divergerebbero alla prima modifica, ed e' esattamente il tipo di
    disallineamento silenzioso che questo refactor serve a eliminare.

    Regole di strict=true che la conversione deve rispettare:
    - additionalProperties: false su ogni oggetto;
    - OGNI property elencata in "required" (gli opzionali si esprimono con
      un tipo unione che include "null", non omettendoli da required);
    - niente propertyOrdering/format:enum (ignorati o rifiutati da OpenAI).
    """
    if not isinstance(schema, dict):
        return schema

    tipo = schema.get("type")
    convertito = {}

    if isinstance(tipo, str):
        tipo_lower = tipo.lower()
        if tipo_lower == "integer":
            tipo_lower = "integer"
        convertito["type"] = [tipo_lower, "null"] if schema.get("nullable") else tipo_lower

    for chiave in ("description", "enum", "minItems", "maxItems"):
        if chiave in schema:
            convertito[chiave] = schema[chiave]

    if "properties" in schema:
        convertito["properties"] = {
            nome: _schema_gemini_to_openai(sotto_schema)
            for nome, sotto_schema in schema["properties"].items()
        }
        # strict=true pretende che TUTTE le property siano in required.
        convertito["required"] = list(schema["properties"].keys())
        convertito["additionalProperties"] = False

    if "items" in schema:
        convertito["items"] = _schema_gemini_to_openai(schema["items"])

    return convertito

CERVELLO_RESPONSE_SCHEMA_OPENAI = _schema_gemini_to_openai(CERVELLO_RESPONSE_SCHEMA)
