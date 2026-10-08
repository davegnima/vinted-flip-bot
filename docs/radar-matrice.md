# Matrice modelli del radar

Generata da `data/radar_matrice.json` (fonti di ogni prezzo in `data/radar_matrice_fonti.json`). Non modificare a mano: si rigenera insieme ai dati.

## Come leggerla
- **Rivendita veloce**: prezzo a cui il modello si vende in 2-3 settimane, ricavato da venduti reali (aste chiuse, eBay venduti via PriceCharting, BrickLink) o, se mancano, dai prezzi chiesti x 0,85. Mai da Vinted.
- **Affidabilita'**: alta = 8+ venduti recenti; media = 3-7; bassa = solo prezzi chiesti o venduti vecchi; insufficiente = meno di 3 confronti. Solo alta e media danno un buy max.
- **Buy max**: prezzo Vinted massimo con margine >= 50 EUR e ROI >= 100% (`bot/radar_matrice.py`): costo = prezzo x 1,05 + 0,70 + spedizione; netto = rivendita x 0,90 - riserva rischio (3% della rivendita per ogni punto di rischio falsi/guasti sopra 2); buy max = il prezzo che lascia costo <= min(netto - 50, netto / 2). Il filtro del radar lascia passare fino a buy max x 1,15 (trattativa).
- **Sotto soglia**: valgono troppo poco usati per un margine di 50 EUR: il radar li scarta. **Non spedibile**: ingombrante senza pacco normale, l'utente non fa ritiri: scartato.
- Limiti noti: molti venduti sono aste nordeuropee (prezzo di martello, senza diritti) o eBay USA/mondo; i prezzi italiani possono essere diversi e non e' stato misurato di quanto. Le scale 1-5 sono stime.

Totale 301 righe: alta 145, bassa 67, media 62, insufficiente 27; 157 con buy max, 72 sotto soglia, 12 non spedibili.

## argento_gioielli (4)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Georg Jensen | Orologio Vivianna (Torun) | 235 | bassa | - | 3 | 1/6 | senza dati |
| Georg Jensen | Moonlight Grapes | 205 | bassa | - | 3 | 3/5 | senza dati |
| Georg Jensen | Daisy (margherita smaltata) | 145 | media | 55 | 3 | 7/7 | attivo |
| Georg Jensen | Posate Acorn (pezzo singolo) | - | insufficiente | - | 2 | 2/2 | sotto soglia |

## arredo_design (31)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| B&B Italia | Le Bambole (Mario Bellini) | 2000 | media | - | 1 | 11/11 | non spedibile |
| B&B Italia | Charles divano (Antonio Citterio) | 1065 | media | - | 1 | 11/11 | non spedibile |
| B&B Italia | Up (Gaetano Pesce) | - | insufficiente | - | 3 | 2/2 | non spedibile |
| B&B Italia | Camaleonda (Mario Bellini) | - | insufficiente | - | 2 | 1/1 | non spedibile |
| Cassina | LC2 poltrona (Le Corbusier) | 1770 | media | - | 5 | 20/20 | non spedibile |
| Cassina | LC4 chaise longue | 1080 | alta | - | 5 | 19/19 | non spedibile |
| Cassina | 699 Superleggera (Gio Ponti) | 270 | media | 88 | 4 | 8/8 | attivo |
| Cassina | Cab 412 sedia (Mario Bellini) | 240 | alta | 73 | 2 | 19/22 | attivo |
| Cassina | Utrecht poltrona (Rietveld) | - | insufficiente | - | 2 | 2/2 | non spedibile |
| Kartell | Universale 4867 sedia (Joe Colombo) | 100 | media | 18 | 1 | 7/7 | attivo |
| Kartell | Masters (Starck & Quitllet) | 70 | alta | - | 4 | 20/20 | sotto soglia |
| Kartell | Componibili (Anna Castelli Ferrieri) | 65 | alta | - | 2 | 20/20 | sotto soglia |
| Kartell | Bookworm (Ron Arad) | 65 | media | - | 2 | 12/12 | sotto soglia |
| Kartell | Louis Ghost (Philippe Starck) | 60 | alta | - | 4 | 20/20 | sotto soglia |
| Vitra | Ball Clock (George Nelson) | 225 | media | 80 | 4 | 17/21 | attivo |
| Vitra | Sunburst Clock (George Nelson) | 200 | media | 67 | 4 | 12/18 | attivo |
| Vitra | Eames Elephant (grande, plastica) | 165 | media | 55 | 2 | 3/15 | attivo |
| Vitra | Uten.Silo I / II | 155 | alta | 52 | 3 | 17/29 | attivo |
| Vitra | Panton Chair vintage Herman Miller / Fehlbaum (1967-1979) | 145 | media | 35 | 3 | 16/28 | attivo |
| Vitra | Hang it all | 135 | alta | 46 | 3 | 20/26 | attivo |
| Vitra | Panton Chair (Vitra, produzione attuale) | 125 | media | 27 | 3 | 20/28 | attivo |
| Vitra | Vitra Design Museum Miniatures Collection (sedie 1:6) | 105 | media | 35 | 2 | 9/21 | attivo |
| Vitra | Wooden Dolls (Alexander Girard) | 90 | bassa | - | 2 | 1/6 | sotto soglia |
| Vitra | Eames House Bird | 85 | media | - | 4 | 10/13 | sotto soglia |
| Vitra | Eames Plastic Side Chair DSW/DSR (singola) | 85 | alta | - | 5 | 20/31 | sotto soglia |
| Vitra | Toolbox (Arik Levy) | 15 | bassa | - | 2 | 0/12 | sotto soglia |
| Zanotta | Quaderna tavolo/tavolino (Superstudio) | 1605 | bassa | - | 2 | 3/3 | non spedibile |
| Zanotta | Mezzadro sgabello (Castiglioni) | 275 | media | 98 | 2 | 5/5 | attivo |
| Zanotta | Sacco poltrona (Gatti Paolini Teodoro) | 180 | bassa | - | 4 | 0/4 | non spedibile |
| Zanotta | Servomuto tavolino (Castiglioni) | 135 | bassa | - | 2 | 4/12 | senza dati |
| Zanotta | Sella sgabello (Castiglioni) | - | insufficiente | - | 2 | 2/2 | senza dati |

## audio (13)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Audeze | LCD-X | 615 | bassa | - | 2 | 1/9 | senza dati |
| Audeze | LCD-2 / LCD-2 Classic | 460 | bassa | - | 2 | 1/9 | senza dati |
| Audeze | Mobius | 80 | bassa | - | 1 | 0/8 | sotto soglia |
| Audeze | LCD-1 | - | insufficiente | - | 1 | 0/2 | senza dati |
| Bang & Olufsen | Beosound 2 (diffusore 2017+) | 1375 | bassa | - | 1 | 0/8 | senza dati |
| Bang & Olufsen | Beogram 4000 / 4002 / 4004 (giradischi) | 930 | bassa | - | 1 | 1/9 | senza dati |
| Bang & Olufsen | Beolit 20 | 325 | bassa | - | 1 | 0/7 | senza dati |
| Bang & Olufsen | Beoplay H95 | 255 | media | 94 | 3 | 3/11 | attivo |
| Bang & Olufsen | Beolit 17 / Beolit 15 | 155 | bassa | - | 1 | 1/7 | senza dati |
| Bang & Olufsen | Beosound 1 (CD/radio) | 135 | media | 41 | 1 | 5/5 | attivo |
| Bang & Olufsen | Beoplay H9 / H9i / H9 3rd Gen | 95 | media | - | 3 | 6/14 | sotto soglia |
| Bang & Olufsen | Beosound A1 / Beoplay A1 | 60 | alta | - | 2 | 9/9 | sotto soglia |
| Bang & Olufsen | Beoplay H6 | - | insufficiente | - | 2 | 2/2 | sotto soglia |

## borse_vintage (14)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Coach | Willis | 160 | bassa | - | 3 | 2/9 | senza dati |
| Coach | Station Bag | 145 | bassa | - | 3 | 2/4 | senza dati |
| Coach | Rambler's Legacy | 135 | bassa | - | 3 | 0/8 | senza dati |
| Coach | Court Bag | 135 | bassa | - | 3 | 1/10 | senza dati |
| Coach | City Bag | - | insufficiente | - | 3 | 1/2 | senza dati |
| Mulberry | Alexa | 380 | media | 143 | 4 | 7/8 | attivo |
| Mulberry | Bayswater | 325 | media | 121 | 4 | 12/12 | attivo |
| Mulberry | Darley | 265 | media | 104 | 3 | 5/5 | attivo |
| Mulberry | Antony | 220 | media | 83 | 3 | 5/5 | attivo |
| Mulberry | Lily | 200 | media | 76 | 3 | 9/9 | attivo |
| Mulberry | Roxanne | 85 | media | - | 3 | 5/5 | sotto soglia |
| Roberta di Camerino | Bagonghi | 295 | bassa | - | 3 | 4/7 | senza dati |
| Roberta di Camerino | Borse in velluto tricolore (non Bagonghi) | 215 | bassa | - | 2 | 7/8 | senza dati |
| Roberta di Camerino | Grace | - | insufficiente | - | 3 | 0/0 | senza dati |

## ceramiche_oggetti (20)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Alessi | 100% Make Up vasi (Mendini, Tendentse) | 125 | bassa | - | 1 | 3/3 | senza dati |
| Alessi | Bombé servizio tè/caffè (Carlo Alessi) | 100 | bassa | - | 1 | 4/7 | senza dati |
| Alessi | La Conica caffettiera (Aldo Rossi) | 80 | bassa | - | 1 | 5/12 | sotto soglia |
| Alessi | Bollitore 9091 (Richard Sapper) | 55 | bassa | - | 1 | 0/12 | sotto soglia |
| Alessi | Plissé (Michele De Lucchi) | 55 | bassa | - | 1 | 1/4 | sotto soglia |
| Alessi | Pulcina caffettiera (Michele De Lucchi) | 50 | bassa | - | 1 | 0/7 | sotto soglia |
| Alessi | Bollitore 9093 (Michael Graves) | 40 | bassa | - | 3 | 0/12 | sotto soglia |
| Alessi | Menage 5070 (Ettore Sottsass) | 35 | bassa | - | 1 | 0/12 | sotto soglia |
| Alessi | Juicy Salif (Philippe Starck) | 25 | media | - | 3 | 14/26 | sotto soglia |
| Alessi | Anna G. cavatappi (Mendini) | 20 | bassa | - | 2 | 2/14 | sotto soglia |
| Alessi | Tea & Coffee Piazza (1983, edizione limitata) | - | insufficiente | - | 1 | 0/0 | senza dati |
| Bitossi | Ceramiche Ettore Sottsass | 515 | bassa | - | 3 | 6/6 | senza dati |
| Bitossi | Vaso Rimini Blu (Aldo Londi, vintage) | 110 | bassa | - | 2 | 0/5 | senza dati |
| Bitossi | Posacenere / ciotola Rimini Blu | 70 | bassa | - | 2 | 2/5 | sotto soglia |
| Bitossi | Gatto Aldo Londi vintage (grande, anni '60) | - | insufficiente | - | 3 | 0/2 | senza dati |
| Bitossi | Gatti e animali Rimini Blu produzione attuale | - | insufficiente | - | 2 | 0/0 | sotto soglia |
| Fornasetti | Posacenere in porcellana | 190 | bassa | - | 3 | 4/5 | senza dati |
| Fornasetti | Piatto Tema e Variazioni | 170 | media | 61 | 3 | 9/9 | attivo |
| Fornasetti | Cuscino | 95 | bassa | - | 4 | 1/6 | sotto soglia |
| Fornasetti | Gettacarte / portaombrelli in metallo | - | insufficiente | - | 3 | 0/1 | senza dati |

## console_retro (40)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Nintendo | Game Boy Color edizione Pokémon in scatola (CIB) | 747 | alta | 279 | 4 | 23/23 | attivo |
| Nintendo | New Nintendo 3DS XL edizioni limitate (Hyrule, Samus, SNES) | 411 | alta | 163 | 2 | 47/47 | attivo |
| Nintendo | Pokémon Cristallo completo in scatola (CIB, PAL) | 373 | alta | 143 | 4 | 24/24 | attivo |
| Nintendo | Pokémon Smeraldo completo in scatola (CIB, PAL) | 357 | alta | 132 | 5 | 22/22 | attivo |
| Nintendo | New Nintendo 3DS XL (standard) | 237 | alta | 91 | 1 | 31/31 | attivo |
| Nintendo | Super Metroid (SNES, PAL, CIB) | 229 | alta | 88 | 3 | 19/19 | attivo |
| Nintendo | Pokémon HeartGold / SoulSilver con Pokéwalker (DS, PAL, CIB) | 194 | alta | 69 | 5 | 20/20 | attivo |
| Nintendo | Pokémon XD: Gale of Darkness (GameCube, PAL) | 186 | alta | 68 | 4 | 23/23 | attivo |
| Nintendo | Game Boy DMG-01 classico in scatola (CIB) | 179 | alta | 63 | 2 | 22/22 | attivo |
| Nintendo | Game Boy Micro | 179 | alta | 68 | 2 | 30/30 | attivo |
| Nintendo | Super Nintendo PAL in scatola (CIB) | 165 | alta | 53 | 1 | 11/11 | attivo |
| Nintendo | Pokémon Argento completo in scatola (CIB, PAL) | 163 | alta | 59 | 4 | 25/25 | attivo |
| Nintendo | Nintendo 3DS Zelda 25th Anniversary | 160 | alta | 59 | 2 | 37/37 | attivo |
| Nintendo | Fire Emblem: Path of Radiance (GameCube, PAL) | 153 | alta | 55 | 4 | 19/19 | attivo |
| Nintendo | Pokémon Rosso completo in scatola (CIB, PAL) | 145 | alta | 52 | 4 | 28/28 | attivo |
| Nintendo | Pokémon Stadium 2 (N64, PAL, CIB) | 143 | alta | 52 | 3 | 20/20 | attivo |
| Nintendo | Pokémon Giallo completo in scatola (CIB, PAL) | 136 | alta | 48 | 4 | 27/27 | attivo |
| Nintendo | Pokémon Blu completo in scatola (CIB, PAL) | 134 | alta | 48 | 4 | 28/28 | attivo |
| Nintendo | Pokémon Oro completo in scatola (CIB, PAL) | 129 | alta | 46 | 4 | 27/27 | attivo |
| Nintendo | Pokémon Smeraldo (cartuccia sola, PAL) | 122 | alta | 42 | 5 | 29/29 | attivo |
| Nintendo | Game Boy Advance SP AGS-101 (retroilluminato, console sola) | 116 | alta | 36 | 4 | 47/47 | attivo |
| Nintendo | Game Boy Color edizione Pokémon (Pikachu) | 108 | alta | 30 | 4 | 25/25 | attivo |
| Nintendo | Zelda Game Boy/GBC completo in scatola (Link's Awakening DX, Oracle of Ages/Seasons) | 107 | alta | 32 | 4 | 75/75 | attivo |
| Nintendo | Game Boy Advance SP Classic NES Edition | 101 | alta | 24 | 4 | 32/32 | attivo |
| Nintendo | Pokémon HeartGold / SoulSilver senza Pokéwalker (DS, PAL, CIB) | 99 | alta | - | 5 | 20/20 | sotto soglia |
| Nintendo | Zelda A Link to the Past (SNES, PAL, CIB) | 95 | alta | - | 3 | 25/25 | sotto soglia |
| Nintendo | Zelda Twilight Princess (GameCube, PAL) | 91 | alta | - | 3 | 23/23 | sotto soglia |
| Nintendo | Game Boy Advance SP AGS-001 (console sola) | 76 | alta | - | 3 | 54/54 | sotto soglia |
| Nintendo | Pokémon Cristallo (cartuccia sola, PAL) | 75 | alta | - | 5 | 30/30 | sotto soglia |
| Nintendo | GameCube (console sola, nero/viola/platino) | 74 | alta | - | 1 | 52/52 | sotto soglia |
| Nintendo | Nintendo 64 (console sola) | 71 | alta | - | 1 | 24/24 | sotto soglia |
| Nintendo | Zelda Ocarina of Time (N64, PAL, CIB) | 64 | alta | - | 3 | 25/25 | sotto soglia |
| Nintendo | Game Boy Advance (AGB-001, console sola) | 63 | alta | - | 3 | 57/57 | sotto soglia |
| Nintendo | Game Boy Color (console sola, colori standard) | 58 | alta | - | 3 | 165/165 | sotto soglia |
| Nintendo | Game Boy DMG-01 classico (console sola) | 48 | alta | - | 2 | 28/28 | sotto soglia |
| Nintendo | Game Boy Pocket (console sola) | 45 | alta | - | 3 | 28/28 | sotto soglia |
| Nintendo | Super Nintendo PAL (console) | 45 | alta | - | 1 | 13/13 | sotto soglia |
| Nintendo | Pokémon Rosso/Blu/Giallo/Oro/Argento (cartuccia sola, PAL) | 28 | alta | - | 5 | 146/146 | sotto soglia |
| Nintendo | Nintendo DS Lite (console sola) | 26 | alta | - | 2 | 29/29 | sotto soglia |
| Nintendo | GameCube giochi popolari (Zelda Wind Waker, Metroid Prime, Pikmin, Smash Bros Melee) | 18 | alta | - | 2 | 71/71 | sotto soglia |

## fotografia (19)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Carl Zeiss (Contax C/Y) | Planar T* 85mm f/1.4 | 285 | media | 115 | 1 | 4/4 | attivo |
| Carl Zeiss (Contax C/Y) | Planar T* 50mm f/1.4 | 175 | media | 68 | 1 | 6/6 | attivo |
| Carl Zeiss (Contax C/Y) | Planar T* 50mm f/1.7 | 90 | alta | - | 1 | 8/8 | sotto soglia |
| Carl Zeiss (Contax G) | Biogon T* 28mm f/2.8 (G) | 320 | media | 130 | 1 | 6/7 | attivo |
| Carl Zeiss (Contax G) | Planar T* 45mm f/2 (G) | 320 | media | 130 | 1 | 5/5 | attivo |
| Carl Zeiss (Contax G) | Biogon T* 21mm f/2.8 (G) | 305 | media | 124 | 1 | 3/4 | attivo |
| Carl Zeiss (Contax G) | Sonnar T* 90mm f/2.8 (G) | 200 | media | 79 | 1 | 3/8 | attivo |
| Contax | T3 | 1920 | media | 759 | 1 | 3/6 | attivo |
| Contax | G2 (corpo) | 1065 | media | 431 | 1 | 7/7 | attivo |
| Contax | T2 | 850 | media | 331 | 1 | 6/14 | attivo |
| Contax | G1 (corpo) | 385 | media | 150 | 1 | 5/7 | attivo |
| Contax | TVS (pellicola) | 180 | alta | 64 | 1 | 11/17 | attivo |
| Contax | RTS III (corpo) | 130 | media | 44 | 1 | 3/3 | attivo |
| Contax | RTS / RTS II (corpo) | 75 | alta | - | 1 | 13/13 | sotto soglia |
| Contax | 139 Quartz (corpo) | 60 | bassa | - | 1 | 3/3 | sotto soglia |
| Minolta | TC-1 | 905 | alta | 355 | 1 | 14/14 | attivo |
| Olympus | mju II (µ[mju:]-II) | 200 | alta | 74 | 1 | 15/23 | attivo |
| Olympus | mju I (µ[mju:]-1) | 80 | alta | - | 1 | 15/15 | sotto soglia |
| Olympus | mju II Zoom (non il mju II) | - | bassa | - | - | 0/0 | sotto soglia |

## golf (12)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Scotty Cameron | TeI3 Teryllium Newport | 395 | alta | 151 | 3 | 8/8 | attivo |
| Scotty Cameron | Super Select Newport 2 / 2+ | 260 | alta | 95 | 3 | 15/18 | attivo |
| Scotty Cameron | Special Select Newport 2 | 225 | alta | 81 | 3 | 10/10 | attivo |
| Scotty Cameron | Newport 2 (tutte le linee) | 210 | alta | 74 | 3 | 15/15 | attivo |
| Scotty Cameron | Special Select Squareback 2 | 205 | alta | 72 | 3 | 12/12 | attivo |
| Scotty Cameron | Phantom X 5 / 5.5 | 195 | alta | 68 | 3 | 12/12 | attivo |
| Scotty Cameron | Select Newport (1) | 185 | alta | 64 | 3 | 12/12 | attivo |
| Scotty Cameron | Newport (classico / Newport 1) | 180 | media | 62 | 3 | 7/7 | attivo |
| Scotty Cameron | Phantom X 7 / 7.5 | 180 | alta | 62 | 3 | 8/8 | attivo |
| Scotty Cameron | Select Newport 2 | 175 | alta | 60 | 3 | 11/14 | attivo |
| Scotty Cameron | Studio Select Newport 2 | 170 | alta | 58 | 3 | 9/9 | attivo |
| Scotty Cameron | Headcover standard (putter) | 30 | alta | - | 4 | 13/21 | sotto soglia |

## illuminazione_design (45)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Artemide | Tolomeo Mega Terra | 270 | media | 96 | 2 | 4/14 | attivo |
| Artemide | Tolomeo Terra / Lettura | 210 | bassa | - | 2 | 0/6 | senza dati |
| Artemide | Nesso | 205 | bassa | - | 3 | 1/5 | senza dati |
| Artemide | Sintesi Tavolo | 140 | bassa | - | 1 | 0/10 | senza dati |
| Artemide | Tolomeo Tavolo (classico) | 115 | alta | 38 | 3 | 12/15 | attivo |
| Artemide | Tolomeo Micro Tavolo | 115 | media | 40 | 3 | 11/21 | attivo |
| Artemide | Tolomeo Mini Tavolo | 105 | alta | 31 | 3 | 26/36 | attivo |
| Artemide | Nessino | 105 | bassa | - | 3 | 2/4 | senza dati |
| Artemide | Eclisse | 100 | media | 30 | 2 | 4/9 | attivo |
| Artemide | Tizio | 90 | alta | - | 2 | 22/30 | sotto soglia |
| Artemide | Dalu | 55 | bassa | - | 2 | 1/3 | sotto soglia |
| Flos | Arco | 800 | media | - | 5 | 16/24 | non spedibile |
| Flos | Taccia Small | 680 | media | 276 | 2 | 13/14 | attivo |
| Flos | Snoopy | 670 | alta | 248 | 4 | 22/29 | attivo |
| Flos | Taccia | 540 | bassa | - | 2 | 2/4 | senza dati |
| Flos | Toio | 430 | media | 164 | 2 | 12/18 | attivo |
| Flos | Gatto | 395 | bassa | - | 1 | 2/5 | senza dati |
| Flos | Spun Light | 235 | media | 88 | 2 | 9/13 | attivo |
| Flos | Parentesi | 170 | media | 64 | 2 | 4/10 | attivo |
| Flos | Glo-Ball | 160 | alta | 53 | 2 | 23/32 | attivo |
| Flos | IC Lights | 135 | alta | 41 | 4 | 21/21 | attivo |
| Flos | Frisbi | 110 | media | 34 | 1 | 6/10 | attivo |
| Flos | Bon Jour / Bon Jour Unplugged | 75 | bassa | - | 2 | 1/4 | sotto soglia |
| Flos | Miss Sissi | 50 | bassa | - | 2 | 2/8 | sotto soglia |
| Flos | Kelvin | 50 | media | - | 1 | 11/21 | sotto soglia |
| Flos | Romeo Moon | 45 | alta | - | 1 | 13/17 | sotto soglia |
| FontanaArte | Fontana (mod. 1853) | 215 | media | 69 | 3 | 6/12 | attivo |
| FontanaArte | Uovo (mod. 2646) | 200 | bassa | - | 4 | 2/4 | senza dati |
| FontanaArte | Bilia | - | insufficiente | - | 3 | 0/8 | senza dati |
| FontanaArte | Pirellina | - | insufficiente | - | 2 | 0/1 | senza dati |
| Foscarini | Caboche | 355 | alta | 127 | 3 | 21/31 | attivo |
| Foscarini | Twiggy Terra (ad arco) | 280 | media | 95 | 2 | 7/15 | attivo |
| Foscarini | Tress | 155 | bassa | - | 1 | 1/7 | senza dati |
| Foscarini | Gregg | 90 | media | - | 2 | 5/9 | sotto soglia |
| Foscarini | Binic | 80 | bassa | - | 2 | 2/6 | sotto soglia |
| Kartell | Bourgie | 115 | alta | 32 | 4 | 29/37 | attivo |
| Kartell | Componibili (contenitore, non lampada) | 70 | alta | - | 2 | 39/49 | sotto soglia |
| Kartell | Take | 35 | media | - | 3 | 10/20 | sotto soglia |
| Kartell | Battery / Big Battery | - | insufficiente | - | 2 | 0/2 | senza dati |
| Luceplan | Titania | 65 | media | - | 2 | 8/18 | sotto soglia |
| Luceplan | Costanza | 35 | media | - | 2 | 8/18 | sotto soglia |
| Luceplan | Berenice | 25 | media | - | 1 | 4/14 | sotto soglia |
| Oluce | Atollo | 525 | media | 182 | 5 | 10/20 | attivo |
| Oluce | Coupé | 370 | media | 143 | 1 | 3/6 | attivo |
| Oluce | Spider | 100 | media | 25 | 1 | 4/14 | attivo |

## lego (73)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| LEGO | 10182 Cafe Corner - nuovo sigillato | 1770 | media | 718 | 3 | 3/3 | attivo |
| LEGO | 75252 Imperial Star Destroyer UCS - nuovo sigillato | 940 | alta | 351 | 4 | 3/3 | attivo |
| LEGO | 75313 AT-AT UCS - nuovo sigillato | 940 | alta | 364 | 3 | 3/3 | attivo |
| LEGO | 10276 Colosseum - nuovo sigillato | 910 | alta | 339 | 4 | 3/3 | attivo |
| LEGO | 75222 Betrayal at Cloud City - nuovo sigillato | 905 | alta | 372 | 2 | 3/3 | attivo |
| LEGO | 75313 AT-AT UCS - usato completo | 775 | alta | 285 | 3 | 3/3 | attivo |
| LEGO | 75159 Death Star UCS (2016) - nuovo sigillato | 745 | alta | 288 | 3 | 3/3 | attivo |
| LEGO | 10188 Death Star (2008) - nuovo sigillato | 745 | media | 299 | 2 | 3/3 | attivo |
| LEGO | 75222 Betrayal at Cloud City - usato completo | 730 | alta | 287 | 2 | 3/3 | attivo |
| LEGO | 75252 Imperial Star Destroyer UCS - usato completo | 615 | alta | 212 | 4 | 3/3 | attivo |
| LEGO | 42100 Liebherr R 9800 Excavator - nuovo sigillato | 580 | alta | 220 | 3 | 3/3 | attivo |
| LEGO | 75159 Death Star UCS (2016) - usato completo | 570 | alta | 208 | 3 | 3/3 | attivo |
| LEGO | 10182 Cafe Corner - usato completo | 570 | alta | 213 | 3 | 3/3 | attivo |
| LEGO | 10276 Colosseum - usato completo | 550 | alta | 187 | 4 | 3/3 | attivo |
| LEGO | 10188 Death Star (2008) - usato completo | 515 | alta | 193 | 2 | 3/3 | attivo |
| LEGO | 75331 The Razor Crest UCS - usato completo | 465 | alta | 166 | 3 | 3/3 | attivo |
| LEGO | 75192 Millennium Falcon UCS - usato completo | 460 | alta | 152 | 4 | 3/3 | attivo |
| LEGO | 75309 Republic Gunship UCS - nuovo sigillato | 430 | alta | 163 | 3 | 3/3 | attivo |
| LEGO | 75181 Y-Wing Starfighter UCS - nuovo sigillato | 430 | alta | 166 | 3 | 3/3 | attivo |
| LEGO | 75060 Slave I UCS - nuovo sigillato | 405 | alta | 155 | 3 | 3/3 | attivo |
| LEGO | 42056 Porsche 911 GT3 RS - usato completo | 405 | alta | 147 | 4 | 3/3 | attivo |
| LEGO | 42131 Cat D11 Bulldozer - usato completo | 375 | alta | 130 | 3 | 3/3 | attivo |
| LEGO | 42055 Bucket Wheel Excavator - nuovo sigillato | 365 | media | 136 | 2 | 3/3 | attivo |
| LEGO | 42009 Mobile Crane MK II - nuovo sigillato | 360 | alta | 134 | 2 | 3/3 | attivo |
| LEGO | 75144 Snowspeeder UCS - nuovo sigillato | 350 | alta | 132 | 3 | 3/3 | attivo |
| LEGO | 21310 Old Fishing Store - nuovo sigillato | 350 | alta | 137 | 2 | 2/2 | attivo |
| LEGO | 21311 Voltron - nuovo sigillato | 350 | alta | 137 | 2 | 2/2 | attivo |
| LEGO | 42083 Bugatti Chiron - nuovo sigillato | 340 | alta | 121 | 4 | 3/3 | attivo |
| LEGO | 42143 Ferrari Daytona SP3 - nuovo sigillato | 340 | alta | 121 | 4 | 3/3 | attivo |
| LEGO | 75290 Mos Eisley Cantina - usato completo | 335 | alta | 123 | 3 | 3/3 | attivo |
| LEGO | 42100 Liebherr R 9800 Excavator - usato completo | 335 | alta | 114 | 3 | 3/3 | attivo |
| LEGO | 42115 Lamborghini Sian FKP 37 - nuovo sigillato | 320 | alta | 113 | 4 | 3/3 | attivo |
| LEGO | 75095 TIE Fighter UCS - nuovo sigillato | 305 | alta | 114 | 3 | 2/2 | attivo |
| LEGO | 75181 Y-Wing Starfighter UCS - usato completo | 295 | alta | 110 | 3 | 3/3 | attivo |
| LEGO | 75309 Republic Gunship UCS - usato completo | 290 | alta | 105 | 3 | 3/3 | attivo |
| LEGO | 75060 Slave I UCS - usato completo | 290 | alta | 108 | 3 | 3/3 | attivo |
| LEGO | 10243 Parisian Restaurant - nuovo sigillato | 290 | alta | 108 | 3 | 3/3 | attivo |
| LEGO | 75144 Snowspeeder UCS - usato completo | 285 | alta | 105 | 3 | 3/3 | attivo |
| LEGO | 42082 Rough Terrain Crane - nuovo sigillato | 275 | alta | 94 | 3 | 3/3 | attivo |
| LEGO | 10260 Downtown Diner - nuovo sigillato | 275 | alta | 101 | 3 | 3/3 | attivo |
| LEGO | 10232 Palace Cinema - nuovo sigillato | 270 | alta | 99 | 3 | 2/2 | attivo |
| LEGO | 42143 Ferrari Daytona SP3 - usato completo | 265 | alta | 91 | 4 | 3/3 | attivo |
| LEGO | 75275 A-wing Starfighter UCS - nuovo sigillato | 260 | alta | 95 | 3 | 2/2 | attivo |
| LEGO | 21310 Old Fishing Store - usato completo | 255 | alta | 97 | 2 | 2/2 | attivo |
| LEGO | 21311 Voltron - usato completo | 255 | alta | 97 | 2 | 2/2 | attivo |
| LEGO | 21322 Pirates of Barracuda Bay - usato completo | 240 | alta | 87 | 3 | 3/3 | attivo |
| LEGO | 10255 Assembly Square - nuovo sigillato | 240 | alta | 84 | 3 | 3/3 | attivo |
| LEGO | 75095 TIE Fighter UCS - usato completo | 215 | alta | 76 | 3 | 2/2 | attivo |
| LEGO | 10232 Palace Cinema - usato completo | 215 | alta | 76 | 3 | 2/2 | attivo |
| LEGO | 42083 Bugatti Chiron - usato completo | 205 | alta | 67 | 4 | 3/3 | attivo |
| LEGO | 10260 Downtown Diner - usato completo | 205 | alta | 72 | 3 | 3/3 | attivo |
| LEGO | 42055 Bucket Wheel Excavator - usato completo | 200 | alta | 63 | 2 | 3/3 | attivo |
| LEGO | 10255 Assembly Square - usato completo | 200 | alta | 67 | 3 | 3/3 | attivo |
| LEGO | 42115 Lamborghini Sian FKP 37 - usato completo | 180 | alta | 57 | 4 | 3/3 | attivo |
| LEGO | 42009 Mobile Crane MK II - usato completo | 180 | alta | 54 | 2 | 3/3 | attivo |
| LEGO | 10243 Parisian Restaurant - usato completo | 180 | alta | 62 | 3 | 3/3 | attivo |
| LEGO | 42082 Rough Terrain Crane - usato completo | 175 | alta | 52 | 3 | 3/3 | attivo |
| LEGO | 21309 NASA Apollo Saturn V - nuovo sigillato | 175 | alta | 60 | 3 | 3/3 | attivo |
| LEGO | 21318 Tree House - nuovo sigillato | 170 | media | 60 | 2 | 3/3 | attivo |
| LEGO | 75275 A-wing Starfighter UCS - usato completo | 165 | alta | 56 | 3 | 2/2 | attivo |
| LEGO | 42096 Porsche 911 RSR - nuovo sigillato | 150 | alta | 52 | 3 | 2/2 | attivo |
| LEGO | 75257 Millennium Falcon (2019, minifig scale) - nuovo sigillato | 145 | alta | 47 | 3 | 2/2 | attivo |
| LEGO | 21306 The Beatles Yellow Submarine - usato completo | 140 | alta | 50 | 2 | 2/2 | attivo |
| LEGO | 10220 Volkswagen T1 Camper Van - nuovo sigillato | 140 | alta | 48 | 3 | 3/3 | attivo |
| LEGO | 21318 Tree House - usato completo | 130 | alta | 43 | 2 | 3/3 | attivo |
| LEGO | 21309 NASA Apollo Saturn V - usato completo | 110 | alta | 31 | 3 | 3/3 | attivo |
| LEGO | 21313 Ship in a Bottle - nuovo sigillato | 105 | alta | 35 | 2 | 2/2 | attivo |
| LEGO | 21321 International Space Station - nuovo sigillato | 95 | alta | - | 2 | 3/3 | sotto soglia |
| LEGO | 42096 Porsche 911 RSR - usato completo | 85 | alta | - | 3 | 2/2 | sotto soglia |
| LEGO | 75257 Millennium Falcon (2019, minifig scale) - usato completo | 80 | alta | - | 3 | 2/2 | sotto soglia |
| LEGO | 10220 Volkswagen T1 Camper Van - usato completo | 65 | alta | - | 3 | 3/3 | sotto soglia |
| LEGO | 21321 International Space Station - usato completo | 60 | alta | - | 2 | 3/3 | sotto soglia |
| LEGO | 21313 Ship in a Bottle - usato completo | 55 | alta | - | 2 | 2/2 | sotto soglia |

## libri (13)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Assouline | The Impossible Collection (Ultimate Collection) | 340 | bassa | - | 1 | 0/8 | senza dati |
| Assouline | Chanel set di 3 (Memoire, cofanetto) | 45 | bassa | - | 1 | 0/8 | sotto soglia |
| Steidl | William Eggleston Los Alamos Revisited (3 vol.) | 535 | bassa | - | 1 | 0/7 | senza dati |
| Steidl | The Little Black Jacket (Lagerfeld / Roitfeld, 2012) | 165 | bassa | - | 1 | 0/8 | senza dati |
| Steidl | Saul Leiter Early Black and White (2 vol.) | 125 | bassa | - | 1 | 1/9 | senza dati |
| Steidl | Robert Frank The Americans (Steidl) | 30 | bassa | - | 1 | 0/8 | sotto soglia |
| Taschen | Helmut Newton BABY SUMO (2020) | 755 | bassa | - | 1 | 0/6 | senza dati |
| Taschen | Jean-Michel Basquiat XL (2018) | 135 | bassa | - | 1 | 0/8 | senza dati |
| Taschen | Peter Beard (2 volumi in cofanetto / XL) | 85 | bassa | - | 1 | 0/7 | sotto soglia |
| Taschen | Helmut Newton SUMO 2009 / 20th Anniversary (formato normale) | 70 | bassa | - | 1 | 2/10 | sotto soglia |
| Taschen | The Stanley Kubrick Archives (Bibliotheca Universalis) | 10 | bassa | - | 1 | 0/8 | sotto soglia |
| Taschen | Helmut Newton SUMO (1999, firmato) | - | insufficiente | - | 2 | 1/7 | non spedibile |
| Taschen | David Hockney A Bigger Book (SUMO) | - | insufficiente | - | 1 | 0/2 | non spedibile |

## occhiali (17)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Cazal | 607 vintage West Germany | 370 | bassa | - | 4 | 0/4 | senza dati |
| Cazal | 616 vintage West Germany | - | insufficiente | - | 4 | 0/1 | senza dati |
| Cazal | 951 vintage | - | insufficiente | - | 4 | 0/0 | senza dati |
| Jacques Marie Mage | Dealan | 515 | bassa | - | 3 | 1/8 | senza dati |
| Jacques Marie Mage | Zephirin | - | insufficiente | - | 3 | 0/0 | senza dati |
| Matsuda | 2809 (vintage e 2809H) | - | insufficiente | - | 3 | 0/1 | senza dati |
| Matsuda | 10601 (10601H) | - | insufficiente | - | 2 | 0/0 | senza dati |
| Matsuda | 2903 | - | insufficiente | - | 2 | 0/0 | senza dati |
| Oliver Peoples | O'Malley | 125 | bassa | - | 2 | 0/4 | senza dati |
| Oliver Peoples | Gregory Peck | - | insufficiente | - | 2 | 0/0 | senza dati |
| Oliver Peoples | Sheldrake | - | insufficiente | - | 2 | 0/1 | senza dati |
| Oliver Peoples | Cary Grant | - | insufficiente | - | 2 | 0/0 | senza dati |
| Persol | Ratti 714 pieghevole vintage | 720 | bassa | - | 3 | 0/5 | senza dati |
| Persol | Ratti 649 vintage (Meflecto) | 310 | bassa | - | 2 | 1/9 | senza dati |
| Persol | Ratti 69218 'Miami Vice' | 285 | bassa | - | 2 | 0/6 | senza dati |
| Persol | 714 / 714SM Steve McQueen (moderno) | 195 | bassa | - | 3 | 1/4 | senza dati |
| Persol | 649 moderno (PO0649) | 55 | bassa | - | 3 | 0/4 | sotto soglia |
