"""Database SQLite in /data/argus.db (contratto, sezione 5).

Una sola connessione protetta da un lucchetto: il servizio scrive dal ciclo asyncio, la visione
legge i vettori registrati da un suo thread.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from .tempo import a_fuso

SCHEMA = """
CREATE TABLE IF NOT EXISTS stato (chiave TEXT PRIMARY KEY, valore TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS giorni (
    data TEXT PRIMARY KEY, scuola INTEGER, arrivo TEXT, riporto INTEGER, verifiche INTEGER,
    studio INTEGER, lavoro INTEGER, agg_distrazione INTEGER, agg_imbroglio INTEGER,
    fatti INTEGER, totale INTEGER, fatta_alle TEXT);
CREATE TABLE IF NOT EXISTS minuti (ora TEXT PRIMARY KEY, data TEXT, classe TEXT, motivo TEXT, aggiunta INTEGER);
CREATE TABLE IF NOT EXISTS episodi (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, inizio TEXT, fine TEXT, minuti INTEGER,
    aggiunta INTEGER, dettagli TEXT);
CREATE TABLE IF NOT EXISTS diario (id INTEGER PRIMARY KEY AUTOINCREMENT, ora TEXT, riga TEXT);
CREATE INDEX IF NOT EXISTS diario_ora ON diario(ora);
CREATE TABLE IF NOT EXISTS registro (id INTEGER PRIMARY KEY AUTOINCREMENT, ora TEXT, tipo TEXT, dettagli TEXT);
CREATE TABLE IF NOT EXISTS modifiche_liste (id TEXT PRIMARY KEY, dati TEXT);
CREATE TABLE IF NOT EXISTS verdetti (chiave TEXT PRIMARY KEY, dominio TEXT, titolo TEXT, esito TEXT, ora TEXT);
CREATE TABLE IF NOT EXISTS lavori (
    id TEXT PRIMARY KEY, stato TEXT, tipo TEXT, creato TEXT, preso_alle TEXT, scade TEXT,
    contesto TEXT, domande TEXT, file TEXT, origine TEXT, risposte TEXT, giudicato_alle TEXT,
    millisecondi INTEGER, modello TEXT);
CREATE TABLE IF NOT EXISTS riconoscimento (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, nome TEXT, modello TEXT, vettore BLOB,
    file TEXT, creato TEXT);
"""


class Database:
    def __init__(self, percorso: Path | str):
        self.percorso = str(percorso)
        if self.percorso != ":memory:":
            Path(self.percorso).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.percorso, check_same_thread=False, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.executescript(SCHEMA)

    def chiudi(self) -> None:
        with self._lock:
            self._con.close()

    def _esegui(self, sql: str, parametri: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._con.execute(sql, parametri)

    def _tutti(self, sql: str, parametri: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._con.execute(sql, parametri).fetchall()

    # --- stato chiave/valore ---
    def leggi_stato(self, chiave: str) -> Any:
        righe = self._tutti("SELECT valore FROM stato WHERE chiave=?", (chiave,))
        return json.loads(righe[0]["valore"]) if righe else None

    def scrivi_stato(self, chiave: str, valore: Any) -> None:
        self._esegui("INSERT INTO stato(chiave, valore) VALUES(?, ?) ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore",
                     (chiave, json.dumps(valore, ensure_ascii=False)))

    # --- giorni, minuti, episodi, registro ---
    def salva_giorno(self, g: dict) -> None:
        self._esegui(
            "INSERT INTO giorni VALUES(:data,:scuola,:arrivo,:riporto,:verifiche,:studio,:lavoro,:agg_distrazione,"
            ":agg_imbroglio,:fatti,:totale,:fatta_alle) ON CONFLICT(data) DO UPDATE SET scuola=excluded.scuola,"
            "arrivo=excluded.arrivo,riporto=excluded.riporto,verifiche=excluded.verifiche,studio=excluded.studio,"
            "lavoro=excluded.lavoro,agg_distrazione=excluded.agg_distrazione,agg_imbroglio=excluded.agg_imbroglio,"
            "fatti=excluded.fatti,totale=excluded.totale,fatta_alle=excluded.fatta_alle", g)

    def giorno(self, data: str) -> dict | None:
        r = self._tutti("SELECT * FROM giorni WHERE data=?", (data,))
        return dict(r[0]) if r else None

    def salva_minuto(self, ora: datetime, classe: str, motivo: str, aggiunta: int) -> None:
        self._esegui("INSERT OR REPLACE INTO minuti VALUES(?,?,?,?,?)",
                     (ora.isoformat(), ora.date().isoformat(), classe, motivo, aggiunta))

    def minuti(self, data: str) -> list[dict]:
        return [dict(r) for r in self._tutti("SELECT * FROM minuti WHERE data=? ORDER BY ora", (data,))]

    def salva_episodio(self, tipo: str, inizio: datetime, fine: datetime, minuti: int, aggiunta: int, dettagli: dict) -> None:
        self._esegui("INSERT INTO episodi(tipo, inizio, fine, minuti, aggiunta, dettagli) VALUES(?,?,?,?,?,?)",
                     (tipo, inizio.isoformat(), fine.isoformat(), minuti, aggiunta, json.dumps(dettagli, ensure_ascii=False)))

    def episodi(self, tipo: str | None = None) -> list[dict]:
        if tipo:
            righe = self._tutti("SELECT * FROM episodi WHERE tipo=? ORDER BY id", (tipo,))
        else:
            righe = self._tutti("SELECT * FROM episodi ORDER BY id")
        return [dict(r) | {"dettagli": json.loads(r["dettagli"] or "{}")} for r in righe]

    def registra(self, ora: datetime, tipo: str, dettagli: dict | None = None) -> None:
        self._esegui("INSERT INTO registro(ora, tipo, dettagli) VALUES(?,?,?)",
                     (ora.isoformat(), tipo, json.dumps(dettagli or {}, ensure_ascii=False, default=str)))

    def registro(self, tipo: str | None = None) -> list[dict]:
        if tipo:
            righe = self._tutti("SELECT * FROM registro WHERE tipo=? ORDER BY id", (tipo,))
        else:
            righe = self._tutti("SELECT * FROM registro ORDER BY id")
        return [dict(r) | {"dettagli": json.loads(r["dettagli"] or "{}")} for r in righe]

    # --- diario ---
    def scrivi_diario(self, ora: datetime, riga: str) -> None:
        self._esegui("INSERT INTO diario(ora, riga) VALUES(?,?)", (ora.isoformat(), riga))

    def diario(self, da: datetime, a: datetime) -> list[str]:
        righe = self._tutti("SELECT riga FROM diario WHERE ora>=? AND ora<? ORDER BY ora", (da.isoformat(), a.isoformat()))
        return [r["riga"] for r in righe]

    def pulisci_diario(self, ora: datetime, giorni: int = 30) -> int:
        limite = (ora - timedelta(days=giorni)).isoformat()
        return self._esegui("DELETE FROM diario WHERE ora<?", (limite,)).rowcount

    # --- liste e verdetti ---
    def modifiche_liste(self) -> list[dict]:
        return [json.loads(r["dati"]) for r in self._tutti("SELECT dati FROM modifiche_liste")]

    def salva_modifica_lista(self, dati: dict) -> None:
        self._esegui("INSERT OR REPLACE INTO modifiche_liste VALUES(?,?)", (dati["id"], json.dumps(dati, ensure_ascii=False)))

    def verdetti(self) -> dict[str, str]:
        """Dal più vecchio al più recente."""
        return {r["chiave"]: r["esito"] for r in self._tutti("SELECT chiave, esito FROM verdetti ORDER BY ora")}

    def ore_verdetti(self) -> dict[str, datetime]:
        return {r["chiave"]: a_fuso(datetime.fromisoformat(r["ora"]))
                for r in self._tutti("SELECT chiave, ora FROM verdetti ORDER BY ora")}

    def togli_verdetto(self, chiave: str) -> None:
        self._esegui("DELETE FROM verdetti WHERE chiave=?", (chiave,))

    def salva_verdetto(self, chiave: str, dominio: str, titolo: str, esito: str, ora: datetime) -> None:
        self._esegui("INSERT OR REPLACE INTO verdetti VALUES(?,?,?,?,?)", (chiave, dominio, titolo, esito, ora.isoformat()))

    def pulisci_verdetti(self, ora: datetime, giorni: int = 30) -> int:
        limite = (ora - timedelta(days=giorni)).isoformat()
        return self._esegui("DELETE FROM verdetti WHERE ora<?", (limite,)).rowcount

    # --- lavori (foto dubbie) ---
    def salva_lavoro(self, lavoro: dict) -> None:
        campi = ("id", "stato", "tipo", "creato", "preso_alle", "scade", "contesto", "domande", "file", "origine",
                 "risposte", "giudicato_alle", "millisecondi", "modello")
        valori = []
        for c in campi:
            v = lavoro.get(c)
            if c in ("domande", "origine", "risposte") and v is not None:
                v = json.dumps(v, ensure_ascii=False)
            valori.append(v)
        self._esegui(f"INSERT OR REPLACE INTO lavori({','.join(campi)}) VALUES({','.join('?' * len(campi))})", tuple(valori))

    def lavori(self, stato: str | None = None) -> list[dict]:
        if stato:
            righe = self._tutti("SELECT * FROM lavori WHERE stato=? ORDER BY creato", (stato,))
        else:
            righe = self._tutti("SELECT * FROM lavori ORDER BY creato")
        risultato = []
        for r in righe:
            d = dict(r)
            for c in ("domande", "origine", "risposte"):
                d[c] = json.loads(d[c]) if d[c] else None
            risultato.append(d)
        return risultato

    def lavoro(self, id_lavoro: str) -> dict | None:
        for d in self.lavori():
            if d["id"] == id_lavoro:
                return d
        return None

    # --- riconoscimento (vettori, non foto) ---
    def salva_vettore(self, tipo: str, nome: str, modello: str | None, vettore: np.ndarray | None, file: str,
                      ora: datetime) -> None:
        """Il vettore può mancare (modelli non ancora caricati): si calcola dopo dalla foto salvata."""
        dati = np.asarray(vettore, dtype=np.float32).tobytes() if vettore is not None else None
        self._esegui("INSERT INTO riconoscimento(tipo, nome, modello, vettore, file, creato) VALUES(?,?,?,?,?,?)",
                     (tipo, nome, modello, dati, file, ora.isoformat()))

    def vettori(self, tipo: str | None = None) -> list[dict]:
        if tipo:
            righe = self._tutti("SELECT * FROM riconoscimento WHERE tipo=? ORDER BY id", (tipo,))
        else:
            righe = self._tutti("SELECT * FROM riconoscimento ORDER BY id")
        return [dict(r) | {"vettore": np.frombuffer(r["vettore"], dtype=np.float32) if r["vettore"] else None}
                for r in righe]

    def nomi_registrati(self, tipo: str) -> list[str]:
        righe = self._tutti("SELECT DISTINCT nome FROM riconoscimento WHERE tipo=? ORDER BY nome COLLATE NOCASE", (tipo,))
        return [r["nome"] for r in righe]

    def togli_registrato(self, tipo: str, nome: str) -> list[str]:
        righe = self._tutti("SELECT file FROM riconoscimento WHERE tipo=? AND lower(nome)=lower(?)", (tipo, nome))
        self._esegui("DELETE FROM riconoscimento WHERE tipo=? AND lower(nome)=lower(?)", (tipo, nome))
        return [r["file"] for r in righe if r["file"]]

    def togli_tipo(self, tipo: str) -> list[str]:
        righe = self._tutti("SELECT file FROM riconoscimento WHERE tipo=?", (tipo,))
        self._esegui("DELETE FROM riconoscimento WHERE tipo=?", (tipo,))
        return [r["file"] for r in righe if r["file"]]

    def aggiorna_vettore(self, id_riga: int, modello: str, vettore: np.ndarray | None) -> None:
        dati = np.asarray(vettore, dtype=np.float32).tobytes() if vettore is not None else None
        self._esegui("UPDATE riconoscimento SET modello=?, vettore=? WHERE id=?", (modello, dati, id_riga))
