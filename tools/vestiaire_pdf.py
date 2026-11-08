"""Estrae gli articoli da PDF salvati dalle pagine di Vestiaire Collective (scheda a due colonne).

Uso: python3 tools/vestiaire_pdf.py uscita.json file1.pdf [file2.pdf ...]
Legge le posizioni delle parole con `pdftotext -bbox` (colonna sinistra/destra secondo la x),
quindi regge anche le pagine con filtri applicati o senza etichette. Nessuna AI.
"""
import html
import json
import re
import statistics
import subprocess
import sys
from collections import Counter

ETICHETTE = {'WE LOVE', 'VINTAGE', 'NEW', 'NUOVO', 'NEW WITH TAG'}
RUMORE = re.compile(r'^(Salva ricerca|Ordina Per|Categoria.*|Designer|Rimuovi.*|Filtri.*|Taglia.*|Prezzo|Condizione.*|Colore.*)$')
FINE = re.compile(r'Comunicazione importante|Precedente|Seguente')
PREZZO = re.compile(r'^([\d.]+) €$')


def righe_colonne(pdf):
    out = subprocess.run(['pdftotext', '-bbox', pdf, '-'], capture_output=True, text=True, check=True).stdout
    larg = float(re.search(r'<page width="([\d.]+)"', out).group(1))
    parole = [(float(x), float(y), html.unescape(t)) for x, y, t in
              re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)"[^>]*>(.*?)</word>', out)]
    col = [[], []]
    for x, y, t in parole:
        col[0 if x < larg / 2 else 1].append((y, x, t))
    risultato = []
    for c in col:
        c.sort()
        righe, cur, y0 = [], [], None
        for y, x, t in c:
            if y0 is not None and abs(y - y0) > 3:
                righe.append(' '.join(w for _, w in sorted(cur)))
                cur = []
            if not cur:
                y0 = y
            cur.append((x, t))
        if cur:
            righe.append(' '.join(w for _, w in sorted(cur)))
        risultato.append(righe)
    return risultato


def parse(pdf):
    art = []
    for righe in righe_colonne(pdf):
        # parte dalla riga "articoli" (intestazione) e si ferma al piede pagina
        testa = [i for i, l in enumerate(righe[:30]) if re.search(r'\d\+? articoli|^Designer$|^Rimuovi|^Ordina Per', l)]
        ini = max(testa) if testa else -1
        fin = next((i for i, l in enumerate(righe) if FINE.search(l)), len(righe))
        tag, cur, visto_prezzo = [], [], False
        for l in righe[ini + 1:fin]:
            l = l.strip()
            if not l or RUMORE.match(l):
                continue
            if l in ETICHETTE or re.fullmatch(r'(WE LOVE|VINTAGE|NEW)( (WE LOVE|VINTAGE|NEW))+', l):
                tag.append(l)
                continue
            if PREZZO.match(l):
                cur.append(l)
                visto_prezzo = True
                continue
            if visto_prezzo:  # riga dopo i prezzi = paese: scheda chiusa
                prezzi = [int(PREZZO.match(t).group(1).replace('.', '')) for t in cur if PREZZO.match(t)]
                testo = [t for t in cur if not PREZZO.match(t)]
                if len(testo) >= 2:
                    art.append({'brand': testo[0], 'titolo': testo[1],
                                'dettagli': ' '.join(testo[2:]) or None,
                                'prezzo_eur': min(prezzi), 'prezzo_prima_eur': max(prezzi) if len(prezzi) > 1 else None,
                                'cuori': None, 'paese': l,
                                'vintage': any('VINTAGE' in t for t in tag), 'tag': ' '.join(tag) or None})
                tag, cur, visto_prezzo = [], [], False
                continue
            cur.append(l)
    return art


if __name__ == '__main__':
    out_path, files = sys.argv[1], sys.argv[2:]
    tutti, visti, per_file = [], set(), []
    for n, f in enumerate(files, 1):
        art = parse(f)
        nuovi = 0
        for a in art:
            a['pagina_pdf'] = n
            chiave = (a['brand'], a['titolo'], a['dettagli'], a['prezzo_eur'], a['paese'])
            if chiave in visti:
                continue
            visti.add(chiave)
            tutti.append(a)
            nuovi += 1
        per_file.append({'pagina_pdf': n, 'articoli_letti': len(art), 'nuovi_dopo_duplicati': nuovi})
    brand = Counter(a['brand'] for a in tutti)
    json.dump({
        'fonte': 'https://it.vestiairecollective.com/we-love/ (PDF salvati dall\'utente, 8/11/2026)',
        'metodo': 'pdftotext -bbox + parser Python (tools/vestiaire_pdf.py), senza AI',
        'n_articoli': len(tutti), 'per_pdf': per_file,
        'campi_mancanti': {'prezzo_eur': sum(a['prezzo_eur'] is None for a in tutti), 'cuori': len(tutti), 'url': len(tutti)},
        'note': ('Titoli troncati dal sito (…). Con due prezzi: prezzo_prima_eur il piu alto, prezzo_eur il piu basso. '
                 'Cuori e URL assenti nei PDF. Duplicati (stesso brand, titolo, dettagli, prezzo, paese) tolti.'),
        'brand_conteggi': dict(brand.most_common()), 'articoli': tutti,
    }, open(out_path, 'w'), ensure_ascii=False, indent=1)
    print(len(tutti), [p['articoli_letti'] for p in per_file])
