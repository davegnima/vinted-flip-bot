# Radar v2: monitorare il non-moda come la moda (proposta del 23/10/2026)

Perche' il radar attuale non rende: riconosce solo i modelli che ho messo in una lista a mano, con prezzi di rivendita miei, e il tracker manda tutto cio' che passa. L'utente compra a occhio qualunque cosa sia sottoprezzata (un set di posate a 7 EUR che online vale 70-80; Dyson a 80 EUR spazzati via in un secondo). La moda funziona perche' cerca per brand, scarta con parole escluse e fa valutare ogni annuncio al worker (stima per brand e categoria da venduti reali, foto con Gemini, comparabili dal vivo, verdetto deterministico).

## Disegno
1. **Ricerche larghe, non per modello**
   - per brand: circa 150 marchi non moda (casa, cucina, audio, utensili, giochi, bici), con la categoria Vinted dove la conosco;
   - per categoria di valore + prezzo basso (es. posate, cristalleria, porcellane, lampade design, vinili, orologi da tavolo) con `price_to` 30-50 EUR e ordine piu' recente: prende "qualunque cosa a 7 EUR" in una categoria che vale.
2. **Valutazione nel worker (come la moda)**, solo per chi passa un filtro economico (parole escluse, spesa max 50 EUR):
   - **comparabili dal vivo**: ricerca testuale su Vinted del titolo pulito (marca + modello + categoria, solo usato) -> prezzi richiesti di 10-20 annunci simili; "mercato verosimile" = 25° percentile x fattore di sconto (trattativa: da calibrare, partenza 0,85);
   - **tetto dal nuovo**: prezzo del nuovo (ricerca Serper, in cache per modello); rivendita usato mai oltre una quota del nuovo (partenza 60%, calibrata per categoria) e comparabili "nuovo con cartellino" esclusi;
   - **Occhio (Gemini) solo sui pochi rimasti**: set completo? condizione? originale?;
   - **verdetto deterministico** (`calcola_verdetto`): margine >= 50 EUR e ROI >= 100%, spedizione e commissione incluse.
3. **Messaggio Telegram** uguale alla moda, con: prezzo, rivendita verosimile (con intervallo), nuovo a ~X, i 3 comparabili piu' vicini con link, motivo del verdetto.
4. **Calibrazione**: 48 ore in modalita' ombra (registra verdetti, non invia), confronto con gli annunci spariti entro 24 ore; poi si accende l'invio. I fattori (0,85 e 60%) si correggono con i dati.

## Costo
- una ricerca di comparabili per candidato che passa il filtro + una ricerca del nuovo per modello nuovo (cache): stima da misurare, ordine di poche migliaia di chiamate al giorno; banda da controllare con `RIEPILOGO BANDA`.
- nessun servizio a pagamento (Gemini con le chiavi gia' presenti).

## Tappe
1. modulo `bot/valore_mercato.py` (comparabili + tetto dal nuovo) con test;
2. modalita' ombra su 20 ricerche, tra cui posate argento/Christofle/Sambonet e Dyson;
3. controllo dei verdetti sui casi dell'utente, poi accensione dell'invio e allargamento a brand e categorie;
4. servizio `vinted-radar` ricreato solo quando la tappa 2 e' pronta (oggi e' stato tolto dall'utente).

## Cosa NON faccio piu'
- liste di modelli con prezzi stimati a mano;
- prompt per cercare prezzi di rivendita sul web aperto (23 modelli, 0 venduti con prezzo).
