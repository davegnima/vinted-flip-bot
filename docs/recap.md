# Recap mattutino: cosa analizzare (routine delle 05:47 Europe/Rome)

Prima stava nel prompt della routine. Dati: log Railway delle ultime 24 h del worker, con le regole di `docs/log.md` (filtri larghi, finestre di 3-6 h, `limit` 500, elaborazione con python/jq da file). Regole generali e preferenze dell'utente: `CLAUDE.md`.

## Classi di mercato (criterio dell'utente, da usare cosi' com'e')
AFFARE = venduto entro 5 min; MEDIO AFFARE = entro 15 min; NORMALE = entro 1 h; NON AFFARE = ancora invenduto (attivo) a 1 h; PRENOTATO = prenotato (offerta del compratore in corso) entro la prima ora, anche se poi si ritira: domanda alta, conta come veloce nella tabella velocita' (dal 8/10; se poi risulta venduto vale la classe di vendita). Dopo 1 h non si ricontrolla piu'. Tempi da t0 = arrivo del messaggio del tracker. Vale per tutti gli annunci scrapati, qualunque esito. Conta come venduto SOLO `stato=venduto`: gli spariti (`rimosso`, `rimosso?`, `n.d.`) si riportano a parte (per brand, tempi, esito del bot) e non entrano in recall, precisione o taratura.
Righe utili: `ESITO ... esito=GIA_VENDUTO`, `RICONTROLLO LAMPO` (serie 15 s, 30 s, 1, 5, 15 min, 1 h), `RICONTROLLO STORIA` e `RICONTROLLO RIAPPARSO` (spariti seguiti fino a 1 h: tornati online = legit check). `ESITO`, `PREAVVISO` e `RICONTROLLO LAMPO` si incrociano con `item=`. Le righe radar (`RADAR |`, `esito=RADAR_L1_*`) restano fuori dal recap moda.

## Calcoli
1. Classi per brand e categoria (fascia di prezzo, titolo tipo), quota istantanei e <= 1 min.
2. Recall: degli AFFARE+MEDIO, quanti erano COMPRA/TRATTA/CHIEDI FOTO e quanti NON COMPRARE o scartati (cosa li accomuna).
3. Precisione: dei COMPRA/TRATTA, quanti AFFARE/MEDIO/NORMALE/NON AFFARE (i NON AFFARE: target gonfiato?).
4. Tempo mediano messaggio -> notifica (footer ⏱) rispetto alle fasce.
5. Per AFFARE e MEDIO: prezzo richiesto vs fair value/target, per tarare il fair price.
6. Con meno di ~30 AFFARE+MEDIO dirlo e riportare solo i numeri.

## Apprendimento dalla rotazione
L'etichetta e' la classe di vendita (solo `venduto`), non il feedback manuale (l'utente compra ~0,5% dei COMPRA). Obiettivo: un semaforo cosi' buono da togliere quasi del tutto il Cervello e tenere il solo controllo di autenticita'. Ogni giorno:
- tasso di rotazione (AFFARE+MEDIO, mediana, quota istantanei) per brand, categoria, condizione, fascia di prezzo, materiale, taglia, venditore, lingua del titolo, n. foto, ora e giorno; segmenti >= 30 annunci con lift e significativita';
- stima di rivendita da rotazione: moltiplicatori da confrontare con `FAIR_VALUE_TABELLA` e `FAIR_VALUE_APPRESO`;
- calibrazione del semaforo (tasso AFFARE/MEDIO per 🟢/🟡/🔴, margine, ROI, confidenza) e proposte su `FAIR_VALUE_*` e `PREAVVISO_*`;
- indice di sostituibilita' del Cervello: recall/precisione del solo semaforo contro COMPRA/TRATTA, serie storica rispetto al recap del giorno prima.
Se i dati non si ricostruiscono dai log, dire quali campi loggare.
Riferimento 5/10: base veloci 26,6%, 🟢 46%, 🟡 29%, 🔴 9%, COMPRA 55%, TRATTA 23%, NON COMPRARE 12%, CHIEDI FOTO 48%. Analisi 4-7/10 in `STATO.md`.

## Monitoraggi aperti
Quelli in "Da controllare" di `STATO.md`, piu': `PREAVVISO |` (push al giorno, `suono=si|no`, precisione e recall sui venduti entro 30 s e 5 min), `Preavviso non inviato`, `Markdown fallita`, `Gemini TIMEOUT`, `key #N NON VALIDA`, `RISERVA |` (anche `PAGAMENTO`), `Pagina annuncio leggera`, `RIEPILOGO BANDA`, `RICONTROLLO RIAPPARSO`.

## Dati da scaricare ogni mattina (metodo dall'8/10)
Dall'8/10 il worker scrive UNA riga per annuncio a fine serie di ricontrolli: `TRACCIATO | item=... | brand=... | prezzo=... | esito=... | margine=... | roi=... | target=... | legit=... | sem=... | sem_base=... | lift=... | fv=... | conf=... | brand_n=... | categoria=... | cond=... | preavviso=... | pref_max=... | pref_serie=15:0,300:3,... | stato=... | classe=... | venduto_s=... | controlli=... | incompleto=si|no | storia=15:attivo,300:venduto,...`. Contiene esito del bot, semaforo (corretto e d'origine), caratteristiche ed esito di vendita: e' il dataset di tutto. Filtro `"| TRACCIATO |"`, finestre da 4-6 h, `limit` 500 (circa 100-150 righe ogni 4 h); controllare sempre `min`/`max` dei timestamp di ogni file e riscaricare i buchi. Dopo il 1 h dall'arrivo si ha l'esito; le righe `TRACCIATO_RADAR` sono del radar e restano fuori. Ora sono seguiti anche gli scartati dopo lo scrape (`SKIP_PRE_GEMINI`, `SKIP_PRE_CERVELLO`, `SKIP_ROSSO`) con la serie ridotta (5 min, 15 min, 1 h): servono a misurare i falsi negativi dei filtri e dell'Occhio. Le serie sopravvivono ai riavvii (tabella `serie_pendenti`): prima ogni deploy uccideva i ricontrolli in corso e mancava l'esito di circa meta' degli annunci.
Solo per i giorni prima dell'8/10 (senza TRACCIATO): `PREAVVISO |` + `RICONTROLLO LAMPO` con `stato=venduto` o `offset=3600s` + `| ESITO |`, in finestre da 4 h.
Timeout di Gemini: tasso per modello e fase = `Gemini TIMEOUT` / (`GEMINI_USO` + `Gemini TIMEOUT`); `GEMINI_USO` riporta `Nms` e `tentativo N` (mediana e p90 per modello; il timeout di una richiesta e' `GEMINI_TIMEOUT_S`, 20 s). Riserva a pagamento: `PAGAMENTO richieste_oggi=N/600` (contatore nel DB: non riparte dopo un riavvio). `CHIEDI ALTRE FOTO`: quota di veloci per brand e fascia di margine (alert: margine > 30 EUR per tutti i brand, tranne Loewe e Arc'teryx a 30 come gli altri; Miu Miu top/canotte scartati a monte a qualunque prezzo).

## Lavoro di ogni mattina: affinare il semaforo (richiesto dall'utente l'8/10)
Non basta riportare numeri: ogni mattina si ragiona su TUTTI gli annunci con esito (non su un campione) e si migliora il sistema, con l'obiettivo di arrivare a usare quasi solo il semaforo e lasciare Occhio e Cervello ai casi incerti, per poi ripetere il metodo su altre nicchie.
1. Scaricare i TRACCIATO e lanciare `python3 tools/aggiorna_velocita.py FILE... --decadimento 0.97`: aggiorna `bot/dati/velocita.json` (veloci/non veloci per brand e per semaforo d'origine; ogni annuncio conta una volta).
2. Misurare il semaforo corretto (`sem`) contro il d'origine (`sem_base`) e contro la velocita': tasso di veloci per 🟢/🟡/🔴, quanti veloci restano nel 🔴, quanti lenti nel 🟢, per brand e per categoria. Guardare brand e categoria dei veloci nel rosso e dei lenti nel verde; guardare anche prezzo (<= 20 EUR vende veloce), rapporto fair value/prezzo e target del Cervello/prezzo, ora del giorno, venditore.
3. Misurare l'accordo con l'Occhio e il Cervello: dove il Cervello da' COMPRA/TRATTA su brand che non ruotano (Max Mara, Cucinelli, Courreges, Fendi, Acne, Missoni...) e dove il semaforo e il Cervello concordano sempre (candidati a saltare il Cervello).
4. Applicare le correzioni con evidenza solida (campione dichiarato): la tabella `velocita.json` (PR automatica, merge a CI verde), le tabelle di fair value (`FAIR_VALUE_*`, es. Loro Piana: target del Cervello 4x il prezzo, fair value rapido 1,2x), le soglie, i filtri; per il prompt del Cervello solo con prove (oggi il target del Cervello non e' gonfiato sui brand lenti: sono i margini/prezzi bassi a farli passare). Poi misurare l'effetto il giorno dopo.
5. Indice di sostituibilita' (serie storica, confrontare col recap del giorno prima): quota di annunci in cui il solo semaforo corretto avrebbe dato lo stesso esito del Cervello sul "vale la pena"; quando in un segmento (brand x fascia) supera una soglia solida e i veloci persi sono pochi, proporre di saltare Cervello/Occhio in quel segmento.
Riferimento 7-8/10 (263 annunci con esito, in-sample, "leave one out" per il brand): 🟢 50% veloci prima, 66% con la correzione; veloci persi nel 🔴 da 21 a 11.

## Vista per brand
Una riga per brand con >= 3 annunci: analizzati, esiti, margine e ROI medi dei COMPRA/TRATTA, quanti qualificano (margine >= 50 EUR e ROI >= 100%), classi con recall e precisione, spariti a parte, preavvisi, falsi/sospetti. Chiudere con 3-5 brand su cui agire. Campioni < 5 annunci vanno segnalati. Se `PANEL |` ha dati, indicare chi diverge dal PRIMARIO.

## Modelli e quota (solo piani gratuiti)
Per ogni modello (PRIMARIO, riserva `RISERVA |`, pannello `PANEL |`): n chiamate, % ok, errori per tipo, latenza mediana/p90, quota gratuita usata (Gemini 500 al giorno per account sui Flash Lite; OpenRouter :free 50 al giorno), allineamento con la realta'. Ranking e instradamento consigliato per Occhio e Cervello. Conteggio delle richieste a pagamento (`PAGAMENTO`) e spesa stimata.

## Come rispondere
Recap in chat, in italiano, breve, con numeri, effort e rischio, in ordine di priorita'. Obiettivo: brand con margine >= 50 EUR e ROI >= 100% senza troppi falsi. L'utente cerca eccezioni: non proporre tetti al ROI, proporre stime piu' accurate.
