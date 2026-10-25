"""Log dei fallimenti Serper (25/10): codice HTTP e corpo, oppure l'eccezione. Mai la chiave."""
from bot import serper_base


class _Risposta:
    def __init__(self, status, testo):
        self.status_code = status
        self.text = testo


def _cattura(monkeypatch):
    messaggi = []
    monkeypatch.setattr(serper_base.log, "warning", lambda *a: messaggi.append(a[0] % a[1:]))
    return messaggi


def test_log_con_risposta_mostra_codice_e_corpo(monkeypatch):
    messaggi = _cattura(monkeypatch)
    serper_base._log_errore_serper("ricerca di prova", resp=_Risposta(402, "Not enough credits"))
    assert messaggi == ["SERPER FALLITO | ricerca di prova | HTTP 402 | corpo=Not enough credits"]


def test_log_con_eccezione_mostra_il_motivo_e_non_la_chiave(monkeypatch):
    messaggi = _cattura(monkeypatch)
    serper_base._log_errore_serper("ricerca di prova", eccezione=TimeoutError("timed out"))
    assert messaggi == ["SERPER FALLITO | ricerca di prova | eccezione=timed out"]
    assert "X-API-KEY" not in messaggi[0]
