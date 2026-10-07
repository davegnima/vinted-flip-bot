# Recap mattutino: cosa analizzare (routine delle 05:47 Europe/Rome)

Prima stava nel prompt della routine. Dati: log Railway delle ultime 24 h del worker, con le regole di `docs/log.md` (filtri larghi, finestre di 3-6 h, `limit` 500, elaborazione con python/jq da file). Regole generali e preferenze dell'utente: `CLAUDE.md`.

## Classi di mercato (criterio dell'utente, da usare cosi' com'e')
AFFARE = venduto entro 5 min; MEDIO AFFARE = entro 15 min; NORMALE = entro 1 h; NON AFFARE = ancora invenduto (attivo/prenotato) a 1 h. Dopo 1 h non si ricontrolla piu'. Tempi da t0 = arrivo del messaggio del tracker. Vale per tutti gli annunci scrapati, qualunque esito. Conta come venduto SOLO `stato=venduto`: gli spariti (`rimosso`, `rimosso?`, `n.d.`) si riportano a parte (per brand, tempi, esito del bot) e non entrano in recall, precisione o taratura.
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

## Dati da scaricare ogni mattina (metodo, dal 7/10)
Il limite di 500 righe per chiamata taglia le finestre lunghe (parte dalle piu' recenti): controllare sempre `min`/`max` dei timestamp di ogni file e riscaricare i buchi. Finestre da 6 h per `ESITO` + `classe=`; finestre da 3 h per `PREAVVISO |` (una riga per annuncio, serve a calibrare il semaforo con `RICONTROLLO LAMPO` via `item=`) e per `RICONTROLLO STORIA` / `RICONTROLLO RIAPPARSO` (spariti seguiti 1 h). Un annuncio conta solo se ha `ESITO` e `classe=` nei dati scaricati: dichiarare quanti ne restano fuori.
Timeout di Gemini: tasso per modello e fase = `Gemini TIMEOUT` / (`GEMINI_USO` + `Gemini TIMEOUT`); dal 7/10 `GEMINI_USO` riporta anche `Nms` (durata della chiamata riuscita) e `tentativo N`: calcolare mediana e p90 per modello e proporre il timeout di conseguenza (oggi 30 s al primo tentativo, 2 timeout di fila = pausa 120 s). Riserva a pagamento: `PAGAMENTO richieste_oggi=N/600` (il contatore ora sta nel DB: sopravvive ai riavvii). `CHIEDI ALTRE FOTO`: quota di veloci per brand e fascia di margine, per tarare l'alert (`SOGLIA_MARGINE_ALERT_CHIEDI_FOTO` 30 EUR; brand esclusi dal margine 50 EUR).

## Vista per brand
Una riga per brand con >= 3 annunci: analizzati, esiti, margine e ROI medi dei COMPRA/TRATTA, quanti qualificano (margine >= 50 EUR e ROI >= 100%), classi con recall e precisione, spariti a parte, preavvisi, falsi/sospetti. Chiudere con 3-5 brand su cui agire. Campioni < 5 annunci vanno segnalati. Se `PANEL |` ha dati, indicare chi diverge dal PRIMARIO.

## Modelli e quota (solo piani gratuiti)
Per ogni modello (PRIMARIO, riserva `RISERVA |`, pannello `PANEL |`): n chiamate, % ok, errori per tipo, latenza mediana/p90, quota gratuita usata (Gemini 500 al giorno per account sui Flash Lite; OpenRouter :free 50 al giorno), allineamento con la realta'. Ranking e instradamento consigliato per Occhio e Cervello. Conteggio delle richieste a pagamento (`PAGAMENTO`) e spesa stimata.

## Come rispondere
Recap in chat, in italiano, breve, con numeri, effort e rischio, in ordine di priorita'. Obiettivo: brand con margine >= 50 EUR e ROI >= 100% senza troppi falsi. L'utente cerca eccezioni: non proporre tetti al ROI, proporre stime piu' accurate.
