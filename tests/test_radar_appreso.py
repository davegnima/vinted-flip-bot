from bot import radar_appreso as ra
from bot.radar import da_cancellare


def _pulisci():
    ra._oss.clear(); ra._gruppi.clear(); ra._contatori.clear(); ra._segnalate.clear()


def test_servono_tre_osservazioni_solide():
    _pulisci()
    assert ra.registra("wii console", 5.0, 8, None, 1000)
    assert ra.registra("wii console", 8.0, 8, None, 1001)
    assert ra.limite_famiglia("wii console", 1002) is None
    ra.registra("wii console", 6.0, 8, None, 1002)
    assert ra.limite_famiglia("wii console", 1003) == 8.0


def test_osservazioni_deboli_non_contano():
    _pulisci()
    assert not ra.registra("x y", 1.0, 3, None, 1)      # pochi comparabili
    assert not ra.registra("x y", 1.0, 9, 1, 1)         # ricerca allargata
    assert not ra.registra("x y", None, 9, None, 1)     # limite ignoto


def test_scarto_sopra_il_limite_con_campione(monkeypatch):
    _pulisci()
    monkeypatch.setattr(ra, "RADAR_APPRESO", True)
    monkeypatch.setattr(ra, "RADAR_APPRESO_CAMPIONE", 3)
    for i in range(3):
        ra.registra("wii console", 10.0, 8, None, 1000 + i)
    assert ra.da_saltare("wii console", 14, 2000) is None       # entro il margine di sicurezza (10 x 1,25 + 2 = 14,5)
    assert ra.da_saltare("wii console", 30, 2000) == 10.0
    assert ra.da_saltare("wii console", 30, 2000) == 10.0
    assert ra.da_saltare("wii console", 30, 2000) is None       # ogni 3 passa il calcolo completo
    assert ra.da_saltare("altra famiglia", 30, 2000) is None    # famiglia sconosciuta


def test_osservazioni_scadute(monkeypatch):
    _pulisci()
    for i in range(3):
        ra.registra("wii console", 10.0, 8, None, 1000 + i)
    assert ra.limite_famiglia("wii console", 1000 + 15 * 86400) is None


def test_spento_con_variabile(monkeypatch):
    _pulisci()
    monkeypatch.setattr(ra, "RADAR_APPRESO", False)
    for i in range(3):
        ra.registra("wii console", 10.0, 8, None, 1000 + i)
    assert ra.da_saltare("wii console", 99, 2000) is None


def test_famiglia_senza_margine_si_cancella_dal_gruppo():
    assert da_cancellare({"semaforo": "rosso", "motivo": "famiglia_senza_margine"})


def test_famiglia_senza_colori_e_condizione():
    assert ra.normalizza("nintendo switch lite grigia") == "nintendo switch lite"
    assert ra.normalizza("ghd platinum nero") == "ghd platinum"
    assert ra.normalizza("wii console") == "wii console"
    assert ra.normalizza("nero bianco") == "nero bianco"      # niente parole utili: resta com'e'
    _pulisci()
    for i, f in enumerate(["nintendo switch lite", "nintendo switch lite grigia", "nintendo switch lite blu"]):
        ra.registra(f, 20.0, 8, None, 1000 + i)
    assert ra.limite_famiglia("nintendo switch lite gialla", 1010) == 20.0     # le tre varianti contano come un mercato


def test_gruppo_impara_da_famiglie_scritte_in_modi_diversi():
    _pulisci()
    # 'nintendo switch lite' scritto in modi diversi: nessuna famiglia arriva a 3, il gruppo (5 osservazioni, 3 famiglie) si
    for fam in ("nintendo switch lite avec", "nintendo switch lite avec", "nintendo switch lite boite",
                "nintendo switch lite boite", "nintendo switch lite chargeur"):
        ra.registra(fam, 30, 8, False, 1000)
    assert ra.limite_famiglia("nintendo switch lite sans", 1000) == 30
    assert ra.da_saltare("nintendo switch lite sans", 100, 1000) == 30


def test_gruppo_non_scatta_con_una_sola_famiglia_o_poche_osservazioni():
    _pulisci()
    for _ in range(6):
        ra.registra("nintendo switch lite avec", 30, 8, False, 1000)
    assert ra.limite_famiglia("nintendo switch lite sans", 1000) is None  # una sola famiglia
    _pulisci()
    for fam in ("nintendo switch lite avec", "nintendo switch lite boite", "nintendo switch lite chargeur"):
        ra.registra(fam, 30, 8, False, 1000)
    assert ra.limite_famiglia("nintendo switch lite sans", 1000) is None  # solo 3 osservazioni


def test_gruppo_usa_il_limite_piu_alto():
    _pulisci()
    for fam, lim in (("nintendo switch lite avec", 30), ("nintendo switch lite boite", 30), ("nintendo switch lite chargeur", 30),
                     ("nintendo switch lite sans", 30), ("nintendo switch lite coque", 90)):
        ra.registra(fam, lim, 8, False, 1000)
    assert ra.limite_famiglia("nintendo switch lite neuve", 1000) == 90
