# Matrice modelli del radar

Generata da `data/radar_matrice.json` (fonti di ogni prezzo in `data/radar_matrice_fonti.json`). Non modificare a mano: si rigenera insieme ai dati.

## Come leggerla
- **Rivendita veloce**: prezzo a cui il modello si vende in 2-3 settimane, ricavato da venduti reali (aste chiuse, eBay venduti via PriceCharting, BrickLink) o, se mancano, dai prezzi chiesti x 0,85. Mai da Vinted.
- **Affidabilita'**: alta = 8+ venduti recenti; media = 3-7; bassa = solo prezzi chiesti o venduti vecchi; insufficiente = meno di 3 confronti. Solo alta e media danno un buy max.
- **Buy max**: prezzo Vinted massimo con margine >= 50 EUR e ROI >= 100% (`bot/radar_matrice.py`): costo = prezzo x 1,05 + 0,70 + spedizione; netto = rivendita x 0,90 - riserva rischio (3% della rivendita per ogni punto di rischio falsi/guasti sopra 2); buy max = il prezzo che lascia costo <= min(netto - 50, netto / 2). Il filtro del radar lascia passare fino a buy max x 1,15 (trattativa).
- **Sotto soglia**: valgono troppo poco usati per un margine di 50 EUR: il radar li scarta. **Non spedibile**: ingombrante senza pacco normale, l'utente non fa ritiri: scartato.
- Limiti noti: molti venduti sono aste nordeuropee (prezzo di martello, senza diritti) o eBay USA/mondo; i prezzi italiani possono essere diversi e non e' stato misurato di quanto. Le scale 1-5 sono stime.

Totale 589 righe: media 255, alta 194, bassa 113, insufficiente 27; 250 con buy max, 258 sotto soglia, 12 non spedibili.

## argento_gioielli (10)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Georg Jensen | Bracciale in argento (sterling, modelli numerati) | 290 | alta | 119 | 2 | 21/21 | attivo |
| Georg Jensen | Orologio Vivianna (Torun) | 235 | bassa | - | 3 | 1/6 | senza dati |
| Georg Jensen | Moonlight Grapes | 205 | bassa | - | 3 | 3/5 | senza dati |
| Georg Jensen | Collana / ciondolo in argento | 175 | alta | 70 | 2 | 40/40 | attivo |
| Georg Jensen | Spilla in argento (Malinowski, Koppel, numerate) | 145 | alta | 57 | 2 | 21/21 | attivo |
| Georg Jensen | Daisy (margherita smaltata) | 145 | media | 55 | 3 | 7/7 | attivo |
| Georg Jensen | Orecchini in argento | 130 | alta | 51 | 2 | 25/25 | attivo |
| Georg Jensen | Anello in argento | 80 | alta | - | 2 | 20/20 | sotto soglia |
| Georg Jensen | Posate Acorn (pezzo singolo) | - | insufficiente | - | 2 | 2/2 | sotto soglia |
| Georg Jensen / Vivianna Torun | Gioielli Torun in argento (bangle Vivianna, Dew Drop, collane a goccia) | 480 | media | 201 | 2 | 13/13 | attivo |

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

## audio (19)

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
| Brionvega | Radio Cubo TS 502 (Zanuso-Sapper) | 65 | bassa | - | 2 | 3/7 | sotto soglia |
| Sennheiser | HD 600 / HD 650 (cuffie aperte) | 150 | alta | 55 | 2 | 10/10 | attivo |
| Sony | MiniDisc Hi-MD MZ-RH1 / MZ-NH1 | 565 | bassa | - | 1 | 1/3 | senza dati |
| Sony | Walkman Professional WM-D6C | 380 | bassa | - | 1 | 0/21 | senza dati |
| Sony | Walkman TPS-L2 (il primo, 1979) | 230 | media | 84 | 2 | 6/10 | attivo |
| Sony | Walkman DD (WM-DD, DDII, DD2, DD3, DD30, DD33, DD9) | 140 | alta | 49 | 1 | 10/24 | attivo |

## bijoux_vintage (3)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Christian Dior | Bijoux vintage (collane e spille Germany) | 80 | alta | - | 4 | 40/40 | sotto soglia |
| Christian Lacroix | Bijoux vintage (spille, orecchini) | 60 | alta | - | 2 | 14/14 | sotto soglia |
| Yves Saint Laurent | Bijoux vintage (orecchini clip, collane, Robert Goossens) | 60 | media | - | 3 | 9/9 | sotto soglia |

## borse_vintage (18)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Bottega Veneta | Borse intrecciato (Hobo, Roma, Cassette, Olimpia, clutch Knot) | 390 | alta | 147 | 4 | 40/40 | attivo |
| Coach | Willis | 160 | bassa | - | 3 | 2/9 | senza dati |
| Coach | Station Bag | 145 | bassa | - | 3 | 2/4 | senza dati |
| Coach | Rambler's Legacy | 135 | bassa | - | 3 | 0/8 | senza dati |
| Coach | Court Bag | 135 | bassa | - | 3 | 1/10 | senza dati |
| Coach | City Bag | - | insufficiente | - | 3 | 1/2 | senza dati |
| Loewe | Amazona (vintage) | 370 | media | 145 | 3 | 10/10 | attivo |
| Longchamp | Borse (Le Pliage, Roseau, pelle) | 75 | alta | - | 3 | 40/40 | sotto soglia |
| Mulberry | Alexa | 380 | media | 143 | 4 | 7/8 | attivo |
| Mulberry | Bayswater | 325 | media | 121 | 4 | 12/12 | attivo |
| Mulberry | Darley | 265 | media | 104 | 3 | 5/5 | attivo |
| Mulberry | Antony | 220 | media | 83 | 3 | 5/5 | attivo |
| Mulberry | Lily | 200 | media | 76 | 3 | 9/9 | attivo |
| Mulberry | Roxanne | 85 | media | - | 3 | 5/5 | sotto soglia |
| Roberta di Camerino | Bagonghi | 295 | bassa | - | 3 | 4/7 | senza dati |
| Roberta di Camerino | Borse in velluto tricolore (non Bagonghi) | 215 | bassa | - | 2 | 7/8 | senza dati |
| Roberta di Camerino | Grace | - | insufficiente | - | 3 | 0/0 | senza dati |
| Salvatore Ferragamo | Borse vintage (Gancini, Vara) | 85 | alta | - | 2 | 20/20 | sotto soglia |

## ceramiche_oggetti (24)

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
| Ericsson | Ericofon (telefono "Cobra") | 30 | alta | - | 1 | 21/21 | sotto soglia |
| Fornasetti | Posacenere in porcellana | 190 | bassa | - | 3 | 4/5 | senza dati |
| Fornasetti | Piatto Tema e Variazioni | 170 | media | 61 | 3 | 9/9 | attivo |
| Fornasetti | Cuscino | 95 | bassa | - | 4 | 1/6 | sotto soglia |
| Fornasetti | Gettacarte / portaombrelli in metallo | - | insufficiente | - | 3 | 0/1 | senza dati |
| Iittala | Vaso Aalto / Savoy | 55 | alta | - | 2 | 22/22 | sotto soglia |
| Kay Bojesen | Scimmia in legno (Monkey) | 70 | alta | - | 3 | 40/40 | sotto soglia |
| Olivetti | Valentine (macchina da scrivere, Sottsass) | 35 | alta | - | 1 | 28/28 | sotto soglia |

## collezionismo (6)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| HP | Calcolatrici HP vintage (11C, 15C, 28C, 41C, 48S/G) | 40 | alta | - | 1 | 22/22 | sotto soglia |
| Hasbro / Takara | Transformers G1 Optimus Prime (1984) sfuso | 35 | media | - | 3 | 5/5 | sotto soglia |
| Hot Toys | Figure 1/6 (MMS/DX/TMS) completa | 105 | alta | 27 | 3 | 34/34 | attivo |
| Montblanc | Meisterstück 149 (stilografica) | 235 | alta | 88 | 4 | 15/15 | attivo |
| Montblanc | Meisterstück 146 / LeGrand (stilografica) | 180 | media | 66 | 4 | 6/6 | attivo |
| Seiko | 6139 Chronograph (Pogue e varianti) | 285 | alta | 108 | 3 | 19/19 | attivo |

## console_retro (49)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Nintendo | Game Boy Color edizione Pokémon in scatola (CIB) | 747 | alta | 279 | 4 | 23/23 | attivo |
| Nintendo | New Nintendo 3DS XL edizioni limitate (Hyrule, Samus, SNES) | 411 | alta | 163 | 2 | 47/47 | attivo |
| Nintendo | Pokémon Cristallo completo in scatola (CIB, PAL) | 373 | alta | 143 | 4 | 24/24 | attivo |
| Nintendo | Pokémon Smeraldo completo in scatola (CIB, PAL) | 357 | alta | 132 | 5 | 22/22 | attivo |
| Nintendo | Conker's Bad Fur Day (N64, PAL, completo in scatola) | 270 | alta | 106 | 3 | 30/30 | attivo |
| Nintendo | New Nintendo 3DS XL (standard) | 237 | alta | 91 | 1 | 31/31 | attivo |
| Nintendo | Super Metroid (SNES, PAL, CIB) | 229 | alta | 88 | 3 | 19/19 | attivo |
| Nintendo | Terranigma (SNES, PAL, completo in scatola) | 205 | alta | 76 | 4 | 30/30 | attivo |
| Nintendo | Game & Watch Zelda ZL-65 (multi screen) | 200 | alta | 78 | 2 | 28/28 | attivo |
| Nintendo | Pokémon HeartGold / SoulSilver con Pokéwalker (DS, PAL, CIB) | 194 | alta | 69 | 5 | 20/20 | attivo |
| Nintendo | Pokémon XD: Gale of Darkness (GameCube, PAL) | 186 | alta | 68 | 4 | 23/23 | attivo |
| Nintendo | Game Boy DMG-01 classico in scatola (CIB) | 179 | alta | 63 | 2 | 22/22 | attivo |
| Nintendo | Game Boy Micro | 179 | alta | 68 | 2 | 30/30 | attivo |
| Nintendo | Super Nintendo PAL in scatola (CIB) | 165 | alta | 53 | 1 | 11/11 | attivo |
| Nintendo | Pokémon Argento completo in scatola (CIB, PAL) | 163 | alta | 59 | 4 | 25/25 | attivo |
| Nintendo | Nintendo 3DS Zelda 25th Anniversary | 160 | alta | 59 | 2 | 37/37 | attivo |
| Nintendo | Game & Watch originali in scatola (Donkey Kong, Mario Bros, Oil Panic, Green House, Octopus...) | 155 | alta | 58 | 2 | 40/40 | attivo |
| Nintendo | Fire Emblem: Path of Radiance (GameCube, PAL) | 153 | alta | 55 | 4 | 19/19 | attivo |
| Nintendo | Pokémon Rosso completo in scatola (CIB, PAL) | 145 | alta | 52 | 4 | 28/28 | attivo |
| Nintendo | Pokémon Stadium 2 (N64, PAL, CIB) | 143 | alta | 52 | 3 | 20/20 | attivo |
| Nintendo | Pokémon Giallo completo in scatola (CIB, PAL) | 136 | alta | 48 | 4 | 27/27 | attivo |
| Nintendo | Pokémon Blu completo in scatola (CIB, PAL) | 134 | alta | 48 | 4 | 28/28 | attivo |
| Nintendo | Pokémon Oro completo in scatola (CIB, PAL) | 129 | alta | 46 | 4 | 27/27 | attivo |
| Nintendo | Conker's Bad Fur Day (N64, PAL, cartuccia) | 125 | alta | 47 | 3 | 30/30 | attivo |
| Nintendo | Pokémon Smeraldo (cartuccia sola, PAL) | 122 | alta | 42 | 5 | 29/29 | attivo |
| Nintendo | Game Boy Advance SP AGS-101 (retroilluminato, console sola) | 116 | alta | 36 | 4 | 47/47 | attivo |
| Nintendo | Game Boy Color edizione Pokémon (Pikachu) | 108 | alta | 30 | 4 | 25/25 | attivo |
| Nintendo | Zelda Game Boy/GBC completo in scatola (Link's Awakening DX, Oracle of Ages/Seasons) | 107 | alta | 32 | 4 | 75/75 | attivo |
| Nintendo | Zelda Majora's Mask (N64, PAL, completo in scatola) | 105 | alta | 33 | 3 | 30/30 | attivo |
| Nintendo | Game Boy Advance SP Classic NES Edition | 101 | alta | 24 | 4 | 32/32 | attivo |
| Nintendo | Pokémon HeartGold / SoulSilver senza Pokéwalker (DS, PAL, CIB) | 99 | alta | - | 5 | 20/20 | sotto soglia |
| Nintendo | Pokémon Nero 2 / Bianco 2 (DS, PAL, completo) | 95 | alta | - | 4 | 40/40 | sotto soglia |
| Nintendo | Zelda A Link to the Past (SNES, PAL, CIB) | 95 | alta | - | 3 | 25/25 | sotto soglia |
| Nintendo | Zelda Twilight Princess (GameCube, PAL) | 91 | alta | - | 3 | 23/23 | sotto soglia |
| Nintendo | Game Boy Advance SP AGS-001 (console sola) | 76 | alta | - | 3 | 54/54 | sotto soglia |
| Nintendo | Pokémon Cristallo (cartuccia sola, PAL) | 75 | alta | - | 5 | 30/30 | sotto soglia |
| Nintendo | GameCube (console sola, nero/viola/platino) | 74 | alta | - | 1 | 52/52 | sotto soglia |
| Nintendo | Nintendo 64 (console sola) | 71 | alta | - | 1 | 24/24 | sotto soglia |
| Nintendo | Game & Watch originali sfuse (senza scatola) | 70 | alta | - | 2 | 40/40 | sotto soglia |
| Nintendo | Zelda Ocarina of Time (N64, PAL, CIB) | 64 | alta | - | 3 | 25/25 | sotto soglia |
| Nintendo | Game Boy Advance (AGB-001, console sola) | 63 | alta | - | 3 | 57/57 | sotto soglia |
| Nintendo | Game Boy Color (console sola, colori standard) | 58 | alta | - | 3 | 165/165 | sotto soglia |
| Nintendo | Game Boy DMG-01 classico (console sola) | 48 | alta | - | 2 | 28/28 | sotto soglia |
| Nintendo | Game Boy Pocket (console sola) | 45 | alta | - | 3 | 28/28 | sotto soglia |
| Nintendo | Super Nintendo PAL (console) | 45 | alta | - | 1 | 13/13 | sotto soglia |
| Nintendo | Pokémon Rosso/Blu/Giallo/Oro/Argento (cartuccia sola, PAL) | 28 | alta | - | 5 | 146/146 | sotto soglia |
| Nintendo | Nintendo DS Lite (console sola) | 26 | alta | - | 2 | 29/29 | sotto soglia |
| Nintendo | GameCube giochi popolari (Zelda Wind Waker, Metroid Prime, Pikmin, Smash Bros Melee) | 18 | alta | - | 2 | 71/71 | sotto soglia |
| Sega | Panzer Dragoon Saga (Saturn, PAL, completo) | 600 | alta | 243 | 3 | 30/30 | attivo |

## fotografia (46)

| Brand | Modello | Rivendita veloce | Affid. | Buy max | Falsi | Venduti/confronti | Stato |
|---|---|---|---|---|---|---|---|
| Canon | FD 50mm f/1.2 (anche L) | 320 | media | 131 | 1 | 10/10 | attivo |
| Canon | FD 55mm f/1.2 (S.S.C.) | 160 | alta | 63 | 1 | 23/23 | attivo |
| Canon | Canonet QL17 G-III | 85 | alta | - | 1 | 19/19 | sotto soglia |
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
| Fujifilm | Klasse W / Klasse S | 1130 | media | 445 | 1 | 6/7 | attivo |
| Fujifilm | Klasse (38mm f/2.6, originale) | 500 | media | 193 | 1 | 3/4 | attivo |
| Konica | Big Mini (BM-201 / BM-301 / BM-302) | 45 | alta | - | 1 | 14/14 | sotto soglia |
| Leica | Minilux (Summarit 40mm f/2.4) | 620 | bassa | - | 1 | 3/13 | senza dati |
| Leica | Elmarit-R 28mm f/2.8 | 280 | alta | 114 | 1 | 27/27 | attivo |
| Leica | Summicron-R 90mm f/2 | 235 | alta | 94 | 1 | 15/15 | attivo |
| Leica | Summicron-R 50mm f/2 | 215 | alta | 86 | 1 | 32/32 | attivo |
| Leica | Mini / Mini II / Mini 3 (compatta 35mm) | 140 | alta | 49 | 1 | 12/14 | attivo |
| Minolta | TC-1 | 905 | alta | 355 | 1 | 14/14 | attivo |
| Minolta | CLE (telemetro M-mount) | 565 | alta | 227 | 1 | 10/17 | attivo |
| Nikon | 28Ti | 855 | media | 347 | 1 | 8/9 | attivo |
| Nikon | 35Ti | 565 | alta | 227 | 1 | 13/17 | attivo |
| Nikon | Nikkor 50mm f/1.2 (AI / AI-S) | 245 | alta | 99 | 1 | 25/25 | attivo |
| Nikon | FE2 (corpo) | 150 | alta | 54 | 1 | 40/40 | attivo |
| Nikon | Nikkor 55mm f/1.2 (Nikkor-S/S.C non-AI e AI) | 150 | alta | 58 | 1 | 11/11 | attivo |
| Nikon | FM2 / FM2n (corpo) | 135 | alta | 50 | 1 | 40/40 | attivo |
| Nikon | L35AF / L35AF2 (Pikaichi) | 105 | alta | 32 | 1 | 14/14 | attivo |
| Olympus | mju II (µ[mju:]-II) | 200 | alta | 74 | 1 | 15/23 | attivo |
| Olympus | Pen F / FT / FV (reflex mezzo formato) | 135 | alta | 51 | 1 | 20/20 | attivo |
| Olympus | mju I (µ[mju:]-1) | 80 | alta | - | 1 | 15/15 | sotto soglia |
| Olympus | XA (telemetro, non XA2/XA3) | 70 | alta | - | 1 | 38/38 | sotto soglia |
| Olympus | mju II Zoom (non il mju II) | - | bassa | - | - | 0/0 | sotto soglia |
| Ricoh | GR1 / GR1s / GR1v (pellicola) | 235 | media | 87 | 1 | 9/12 | attivo |
| Rollei | 35 S / 35 SE (Sonnar 40mm f/2.8) | 175 | alta | 68 | 1 | 37/40 | attivo |
| Rollei | 35 / 35 T / 35 TE (Tessar 40mm f/3.5) | 110 | alta | 40 | 1 | 26/26 | attivo |
| Yashica | T5 / T4 Super D | 315 | media | 119 | 1 | 6/16 | attivo |
| Yashica | T4 / T4 Super / T4 D (compatta 35mm Zeiss Tessar) | 160 | media | 57 | 1 | 7/22 | attivo |
| Yashica | Yashica-Mat 124 G (biottica 6x6) | 140 | alta | 50 | 1 | 13/13 | attivo |

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

## illuminazione_design (47)

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
| Louis Poulsen | Panthella Mini (Verner Panton) | 190 | media | 66 | 3 | 7/7 | attivo |
| Luceplan | Titania | 65 | media | - | 2 | 8/18 | sotto soglia |
| Luceplan | Costanza | 35 | media | - | 2 | 8/18 | sotto soglia |
| Luceplan | Berenice | 25 | media | - | 1 | 4/14 | sotto soglia |
| Oluce | Atollo | 525 | media | 182 | 5 | 10/20 | attivo |
| Oluce | Coupé | 370 | media | 143 | 1 | 3/6 | attivo |
| Oluce | Spider | 100 | media | 25 | 1 | 4/14 | attivo |
| Vitra Design Museum | Miniature 1:6 (Panton, Wassily, LC4, Thunderball, Eames) | 100 | media | 27 | 3 | 11/11 | attivo |

## lego (292)

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
| LEGO | 10195 Republic Dropship with AT-OT Walker | 743 | media | 293 | 3 | 3/3 | attivo |
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
| LEGO | 75098 Assault on Hoth | 349 | media | 130 | 3 | 4/4 | attivo |
| LEGO | 42083 Bugatti Chiron - nuovo sigillato | 340 | alta | 121 | 4 | 3/3 | attivo |
| LEGO | 42143 Ferrari Daytona SP3 - nuovo sigillato | 340 | alta | 121 | 4 | 3/3 | attivo |
| LEGO | 75290 Mos Eisley Cantina - usato completo | 335 | alta | 123 | 3 | 3/3 | attivo |
| LEGO | 42100 Liebherr R 9800 Excavator - usato completo | 335 | alta | 114 | 3 | 3/3 | attivo |
| LEGO | 9494 Anakin's Jedi Interceptor sigillato | 324 | media | 128 | 3 | 4/4 | attivo |
| LEGO | 42115 Lamborghini Sian FKP 37 - nuovo sigillato | 320 | alta | 113 | 4 | 3/3 | attivo |
| LEGO | 75095 TIE Fighter UCS - nuovo sigillato | 305 | alta | 114 | 3 | 2/2 | attivo |
| LEGO | 7259 ARC-170 Fighter sigillato | 300 | media | 118 | 3 | 4/4 | attivo |
| LEGO | 75181 Y-Wing Starfighter UCS - usato completo | 295 | alta | 110 | 3 | 3/3 | attivo |
| LEGO | 75309 Republic Gunship UCS - usato completo | 290 | alta | 105 | 3 | 3/3 | attivo |
| LEGO | 75060 Slave I UCS - usato completo | 290 | alta | 108 | 3 | 3/3 | attivo |
| LEGO | 10243 Parisian Restaurant - nuovo sigillato | 290 | alta | 108 | 3 | 3/3 | attivo |
| LEGO | 75144 Snowspeeder UCS - usato completo | 285 | alta | 105 | 3 | 3/3 | attivo |
| LEGO | 42082 Rough Terrain Crane - nuovo sigillato | 275 | alta | 94 | 3 | 3/3 | attivo |
| LEGO | 10260 Downtown Diner - nuovo sigillato | 275 | alta | 101 | 3 | 3/3 | attivo |
| LEGO | 75021 Republic Gunship (2013) | 274 | media | 99 | 3 | 4/4 | attivo |
| LEGO | 7662 Trade Federation MTT | 273 | media | 99 | 3 | 4/4 | attivo |
| LEGO | 10232 Palace Cinema - nuovo sigillato | 270 | alta | 99 | 3 | 2/2 | attivo |
| LEGO | 42143 Ferrari Daytona SP3 - usato completo | 265 | alta | 91 | 4 | 3/3 | attivo |
| LEGO | 75275 A-wing Starfighter UCS - nuovo sigillato | 260 | alta | 95 | 3 | 2/2 | attivo |
| LEGO | 9516 Jabba's Palace | 259 | media | 93 | 3 | 4/4 | attivo |
| LEGO | 7673 MagnaGuard Starfighter sigillato | 256 | media | 98 | 3 | 4/4 | attivo |
| LEGO | 21310 Old Fishing Store - usato completo | 255 | alta | 97 | 2 | 2/2 | attivo |
| LEGO | 21311 Voltron - usato completo | 255 | alta | 97 | 2 | 2/2 | attivo |
| LEGO | 10144 Sandcrawler | 242 | media | 86 | 3 | 4/4 | attivo |
| LEGO | 7261 Clone Turbo Tank (2005) | 241 | media | 85 | 3 | 4/4 | attivo |
| LEGO | 21322 Pirates of Barracuda Bay - usato completo | 240 | alta | 87 | 3 | 3/3 | attivo |
| LEGO | 10255 Assembly Square - nuovo sigillato | 240 | alta | 84 | 3 | 3/3 | attivo |
| LEGO | 8043 Motorized Excavator | 233 | media | 79 | 3 | 4/4 | attivo |
| LEGO | 7676 Republic Attack Gunship | 223 | media | 78 | 3 | 3/3 | attivo |
| LEGO | 8098 Clone Turbo Tank (2010) | 223 | media | 78 | 3 | 4/4 | attivo |
| LEGO | 7964 Republic Frigate | 223 | media | 78 | 3 | 4/4 | attivo |
| LEGO | 75095 TIE Fighter UCS - usato completo | 215 | alta | 76 | 3 | 2/2 | attivo |
| LEGO | 10232 Palace Cinema - usato completo | 215 | alta | 76 | 3 | 2/2 | attivo |
| LEGO | 8880 Super Car (1994) | 212 | media | 73 | 3 | 4/4 | attivo |
| LEGO | 10186 General Grievous (Ultimate Collector) | 206 | media | 71 | 3 | 4/4 | attivo |
| LEGO | 42083 Bugatti Chiron - usato completo | 205 | alta | 67 | 4 | 3/3 | attivo |
| LEGO | 10260 Downtown Diner - usato completo | 205 | alta | 72 | 3 | 3/3 | attivo |
| LEGO | 42055 Bucket Wheel Excavator - usato completo | 200 | alta | 63 | 2 | 3/3 | attivo |
| LEGO | 10255 Assembly Square - usato completo | 200 | alta | 67 | 3 | 3/3 | attivo |
| LEGO | 42030 Volvo L350F Wheel Loader | 195 | media | 64 | 3 | 4/4 | attivo |
| LEGO | 75050 B-Wing sigillato | 187 | media | 70 | 3 | 4/4 | attivo |
| LEGO | 42115 Lamborghini Sian FKP 37 - usato completo | 180 | alta | 57 | 4 | 3/3 | attivo |
| LEGO | 42009 Mobile Crane MK II - usato completo | 180 | alta | 54 | 2 | 3/3 | attivo |
| LEGO | 10243 Parisian Restaurant - usato completo | 180 | alta | 62 | 3 | 3/3 | attivo |
| LEGO | 42082 Rough Terrain Crane - usato completo | 175 | alta | 52 | 3 | 3/3 | attivo |
| LEGO | 21309 NASA Apollo Saturn V - nuovo sigillato | 175 | alta | 60 | 3 | 3/3 | attivo |
| LEGO | 21318 Tree House - nuovo sigillato | 170 | media | 60 | 2 | 3/3 | attivo |
| LEGO | 42228 McLaren MCL39 F1 sigillato | 170 | bassa | - | 3 | 0/2 | senza dati |
| LEGO | 75275 A-wing Starfighter UCS - usato completo | 165 | alta | 56 | 3 | 2/2 | attivo |
| LEGO | 42214 Lamborghini Revuelto sigillato | 165 | bassa | - | 3 | 0/2 | senza dati |
| LEGO | 7251 Darth Vader Transformation sigillato | 165 | media | 62 | 3 | 4/4 | attivo |
| LEGO | 7961 Darth Maul's Sith Infiltrator sigillato | 164 | media | 60 | 3 | 4/4 | attivo |
| LEGO | 7672 Rogue Shadow | 162 | media | 53 | 3 | 4/4 | attivo |
| LEGO | 8263 Snow Groomer sigillato | 158 | media | 58 | 3 | 4/4 | attivo |
| LEGO | 8421 Mobile Crane (2005) | 154 | media | 47 | 3 | 4/4 | attivo |
| LEGO | 42096 Porsche 911 RSR - nuovo sigillato | 150 | alta | 52 | 3 | 2/2 | attivo |
| LEGO | 42099 4x4 X-Treme Off-Roader | 150 | media | 45 | 3 | 4/4 | attivo |
| LEGO | 21303 WALL-E | 148 | media | 56 | 2 | 4/4 | attivo |
| LEGO | 75257 Millennium Falcon (2019, minifig scale) - nuovo sigillato | 145 | alta | 47 | 3 | 2/2 | attivo |
| LEGO | 75102 Poe's X-wing Fighter sigillato | 142 | media | 51 | 3 | 4/4 | attivo |
| LEGO | 21306 The Beatles Yellow Submarine - usato completo | 140 | alta | 50 | 2 | 2/2 | attivo |
| LEGO | 10220 Volkswagen T1 Camper Van - nuovo sigillato | 140 | alta | 48 | 3 | 3/3 | attivo |
| LEGO | 42111 Dom's Dodge Charger sigillato | 139 | media | 43 | 3 | 4/4 | attivo |
| LEGO | 7754 Home One Mon Calamari Star Cruiser | 136 | media | 42 | 3 | 3/3 | attivo |
| LEGO | 42063 BMW R 1200 GS Adventure sigillato | 133 | media | 47 | 3 | 4/4 | attivo |
| LEGO | 42224 Porsche 911 GT3 R REXY sigillato | 132 | bassa | - | 3 | 0/1 | senza dati |
| LEGO | 75413 Republic Juggernaut sigillato | 131 | bassa | - | 3 | 0/2 | senza dati |
| LEGO | 21318 Tree House - usato completo | 130 | alta | 43 | 2 | 3/3 | attivo |
| LEGO | 7957 Sith Nightspeeder sigillato | 130 | media | 48 | 3 | 4/4 | attivo |
| LEGO | 75022 Mandalorian Speeder sigillato | 130 | media | 48 | 3 | 4/4 | attivo |
| LEGO | 75135 Obi-Wan's Jedi Interceptor sigillato | 127 | media | 47 | 3 | 4/4 | attivo |
| LEGO | 7751 Ahsoka's Starfighter and Droids | 126 | media | 46 | 3 | 4/4 | attivo |
| LEGO | 75218 X-wing Starfighter sigillato | 125 | media | 44 | 3 | 4/4 | attivo |
| LEGO | 42094 Tracked Loader sigillato | 125 | media | 44 | 3 | 4/4 | attivo |
| LEGO | 75038 Jedi Interceptor sigillato | 125 | media | 46 | 3 | 4/4 | attivo |
| LEGO | 75314 The Bad Batch Attack Shuttle | 123 | media | 36 | 3 | 4/4 | attivo |
| LEGO | 8275 Motorized Bulldozer | 123 | media | 35 | 3 | 4/4 | attivo |
| LEGO | 75152 Imperial Assault Hovertank sigillato | 118 | media | 43 | 3 | 4/4 | attivo |
| LEGO | 8016 Hyena Droid Bomber sigillato | 116 | media | 42 | 3 | 4/4 | attivo |
| LEGO | 9493 X-wing Starfighter (2012) sigillato | 115 | media | 40 | 3 | 4/4 | attivo |
| LEGO | 9488 Elite Clone Trooper & Commando Droid Battle Pack sigillato | 112 | media | 39 | 3 | 4/4 | attivo |
| LEGO | 21309 NASA Apollo Saturn V - usato completo | 110 | alta | 31 | 3 | 3/3 | attivo |
| LEGO | 75048 Rebels The Phantom sigillato | 110 | media | 38 | 3 | 4/4 | attivo |
| LEGO | 42079 Heavy Duty Forklift sigillato | 109 | media | 35 | 3 | 4/4 | attivo |
| LEGO | 8088 ARC-170 Starfighter (2010) | 109 | media | 35 | 3 | 4/4 | attivo |
| LEGO | 21313 Ship in a Bottle - nuovo sigillato | 105 | alta | 35 | 2 | 2/2 | attivo |
| LEGO | 42140 App-Controlled Transformation Vehicle | 105 | media | 22 | 3 | 4/4 | attivo |
| LEGO | 75230 Porg sigillato | 104 | media | 31 | 3 | 4/4 | attivo |
| LEGO | 42210 Nissan Skyline GT-R R34 sigillato | 100 | bassa | - | 3 | 0/2 | senza dati |
| LEGO | 42209 Volvo L120 Electric Wheel Loader | 98 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 21321 International Space Station - nuovo sigillato | 95 | alta | - | 2 | 3/3 | sotto soglia |
| LEGO | 42236 Custom Garage Ford Mustang | 93 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 42096 Porsche 911 RSR - usato completo | 85 | alta | - | 3 | 2/2 | sotto soglia |
| LEGO | 75257 Millennium Falcon (2019, minifig scale) - usato completo | 80 | alta | - | 3 | 2/2 | sotto soglia |
| LEGO | 10220 Volkswagen T1 Camper Van - usato completo | 65 | alta | - | 3 | 3/3 | sotto soglia |
| LEGO | 75429 AT-AT Driver Helmet | 63 | bassa | - | 2 | 0/1 | sotto soglia |
| LEGO | 75441 Venator-Class Attack Cruiser Starship Collection | 62 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75375 Millennium Falcon Starship Collection | 61 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 21321 International Space Station - usato completo | 60 | alta | - | 2 | 3/3 | sotto soglia |
| LEGO | 21320 Dinosaur Fossils | 59 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75036 Utapau Troopers | 58 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75035 Kashyyyk Troopers | 58 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42235 Ferrari 488 Pista | 58 | bassa | - | 2 | 0/1 | sotto soglia |
| LEGO | 76347 Marvel Avengers Doomsday Quinjet | 57 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 21313 Ship in a Bottle - usato completo | 55 | alta | - | 2 | 2/2 | sotto soglia |
| LEGO | 75353 Endor Speeder Chase Diorama | 55 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42226 BMW M4 GT3 EVO | 55 | bassa | - | 2 | 0/1 | sotto soglia |
| LEGO | 75408 Jango Fett Helmet | 54 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 40806 Gingerbread AT-AT | 54 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75356 Executor Super Star Destroyer | 51 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75349 Captain Rex Helmet | 51 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 40796 Revenge of the Sith Heroes & Villains | 51 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75402 ARC-170 Starfighter | 50 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75328 The Mandalorian Helmet | 49 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75433 Jango Fett's Starship | 49 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 42222 Bugatti Chiron Pur Sport | 49 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75432 V-19 Torrent Starfighter | 49 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 21362 Mineral Collection | 47 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75202 Defense of Crait | 46 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 76974 Jurassic World Mosasaurus Boat Mission | 46 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75407 Brick-Built Logo | 45 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 42205 Chevrolet Corvette Stingray | 45 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 42208 Aston Martin Valkyrie | 45 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 42204 Fast & Furious Toyota Supra MK4 | 45 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75347 TIE Bomber | 44 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75439 Darth Vader Bust | 42 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75278 D-O | 40 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75395 Advent Calendar 2024 | 40 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75451 Hutt Palace Sentry Droid Showdown | 40 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 7913 Clone Trooper Battle Pack | 39 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 40755 Imperial Dropship vs Rebel Scout Speeder | 39 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42162 Bugatti Bolide Agile Blue | 39 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42062 Container Yard | 38 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42173 Koenigsegg Jesko Absolut | 38 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75281 Anakin's Jedi Interceptor (2020) | 38 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42121 Heavy Duty Excavator | 38 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42203 Dump Truck | 36 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75089 Geonosis Troopers | 35 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75258 Anakin's Podracer 20th Anniversary | 34 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75534 Darth Vader buildable figure | 34 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42049 Mine Loader | 34 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75385 Ahsoka Battle on Peridea | 33 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75387 Boarding the Tantive IV | 33 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42155 The Batman Batcycle | 33 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75431 327th Star Corps Battle Pack | 32 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 3866 Games The Battle of Hoth | 32 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75404 Acclamator-Class Assault Ship | 31 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75420 SMART Play Luke's Landspeeder | 31 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 60492 City Passenger Jet | 31 | bassa | - | 2 | 0/1 | sotto soglia |
| LEGO | 75456 Advent Calendar 2026 | 31 | bassa | - | 2 | 0/1 | sotto soglia |
| LEGO | 75444 AT-RT Attack | 31 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 42107 Ducati Panigale V4 R | 30 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75262 Imperial Dropship 20th Anniversary | 30 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75301 Luke Skywalker's X-wing Fighter | 30 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 7200 Final Duel I | 29 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75388 Jedi Bob's Starfighter | 29 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75167 Bounty Hunter Speeder Bike Battle Pack | 29 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 40686 Trade Federation Troop Carrier | 28 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42106 Stunt Show Truck & Bike | 28 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75000 Clone Troopers vs Droidekas | 27 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75280 501st Legion Clone Troopers | 27 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75002 AT-RT | 27 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42201 Deep-Sea Research Submarine | 27 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 42219 Monster Jam Grave Digger Fire and Ice | 27 | bassa | - | 2 | 0/1 | sotto soglia |
| LEGO | 75358 Tenoo Jedi Temple | 26 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75437 Cobb Vanth's Speeder | 26 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75300 Imperial TIE Fighter | 25 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 40765 Kamino Training Facility | 25 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 7657 AT-ST (2007) | 25 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75334 Obi-Wan Kenobi vs Darth Vader | 24 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 9490 Droid Escape | 24 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75208 Yoda's Hut | 23 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75137 Carbon-Freezing Chamber | 23 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42075 First Responder | 23 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75271 Luke Skywalker's Landspeeder | 23 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42137 Porsche 99X Electric | 22 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 8092 Luke's Landspeeder | 22 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75312 Boba Fett's Starship | 22 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 8248 Forklift (1998) | 22 | media | - | 2 | 3/3 | sotto soglia |
| LEGO | 75342 Republic Fighter Tank | 21 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75100 First Order Snowspeeder | 21 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75254 AT-ST Raider | 21 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75372 Clone Trooper & Battle Droid Battle Pack | 21 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 75010 B-Wing Starfighter & Planet Endor | 21 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75200 Ahch-To Island Training | 21 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75237 4+ TIE Fighter Attack | 20 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75127 Microfighters The Ghost | 20 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75164 Rebel Trooper Battle Pack (Rogue One) | 20 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75529 Elite Praetorian Guard buildable figure | 19 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75076 Microfighters Republic Gunship | 19 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42074 Racing Yacht | 18 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42048 Race Kart | 18 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75378 BARC Speeder Escape | 18 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42149 Monster Jam Dragon | 18 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75449 Siege of Mandalore Battle Pack | 18 | bassa | - | 2 | 0/2 | sotto soglia |
| LEGO | 7915 Imperial V-wing Starfighter | 18 | media | - | 2 | 3/3 | sotto soglia |
| LEGO | 40448 Vintage Car | 17 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42093 Chevrolet Corvette ZR1 | 17 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75320 Snowtrooper Battle Pack | 17 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75028 Microfighters Clone Turbo Tank | 16 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 40658 Millennium Falcon Holiday Diorama | 16 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 40547 Obi-Wan Kenobi & Darth Vader | 16 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42060 Roadwork Crew | 16 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75310 Duel on Mandalore | 15 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75195 Ski Speeder vs First Order Walker Microfighters | 15 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75247 4+ Rebel A-wing | 15 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 7914 Mandalorian Battle Pack | 14 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75345 501st Clone Troopers Battle Pack | 14 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 8712 Figures (1988) | 14 | media | - | 2 | 3/3 | sotto soglia |
| LEGO | 75373 Ambush on Mandalore Battle Pack | 14 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42164 Off-Road Race Buggy | 14 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75368 Darth Vader Mech | 14 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42092 Rescue Helicopter | 13 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42011 Race Car pull-back | 13 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42119 Monster Jam Max D | 13 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 8083 Rebel Trooper Battle Pack | 13 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75299 Trouble on Tatooine | 13 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 8222 VTOL (1997) | 13 | media | - | 2 | 3/3 | sotto soglia |
| LEGO | 75072 Microfighters ARC-170 | 13 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 8826 ATX Sport Cycle | 13 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42150 Monster Jam Monster Mutt Dalmatian | 12 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75535 Han Solo buildable figure | 12 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75370 Stormtrooper Mech | 12 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 40615 Tusken Raider | 11 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42147 Dump Truck (2023) | 11 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 40676 The Phantom Menace | 10 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75132 First Order Battle Pack | 10 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42218 John Deere 1470H Harvester | 10 | bassa | - | 2 | 0/1 | sotto soglia |
| LEGO | 75130 Microfighters AT-DP | 10 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 40539 Ahsoka Tano | 9 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42118 Monster Jam Grave Digger | 9 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42134 Monster Jam Megalodon | 9 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42103 Dragster | 9 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75032 Microfighters X-Wing | 9 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75131 Resistance Trooper Battle Pack | 9 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42163 Heavy-Duty Bulldozer | 9 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42046 Getaway Racer | 9 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42032 Compact Tracked Loader | 9 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75117 Kylo Ren buildable figure | 8 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75031 Microfighters TIE Interceptor | 8 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75223 Naboo Starfighter Microfighter | 8 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75363 Mandalorian N-1 Microfighter | 8 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42047 Police Interceptor | 7 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42090 Getaway Truck | 7 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42089 Power Boat | 7 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75317 The Mandalorian & The Child | 7 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42045 Hydroplane Racer | 7 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75194 First Order TIE Fighter Microfighter | 7 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42034 Quad Bike | 7 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42026 Black Champion Racer | 6 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42072 WHACK! | 6 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 8065 Mini Container Truck | 6 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42088 Cherry Picker (2019) | 5 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75321 Razor Crest Microfighter | 5 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42073 BASH! | 5 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42101 Buggy | 5 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42133 Telehandler | 4 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42031 Cherry Picker (2015) | 4 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 75295 Millennium Falcon Microfighter | 4 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42117 Race Plane | 4 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 42020 Twin Rotor Helicopter | 4 | media | - | 2 | 4/4 | sotto soglia |
| LEGO | 8207 Dune Duster | 4 | media | - | 2 | 4/4 | sotto soglia |

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

## occhiali (19)

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
| Porsche Design by Carrera | 5621 pieghevole (aviator vintage, Austria) | 100 | bassa | - | 3 | 1/24 | senza dati |
| Ray-Ban (Bausch & Lomb) | Vintage B&L USA (Wayfarer, Aviator, Olympian, Clubmaster) | 45 | alta | - | 4 | 18/40 | sotto soglia |
