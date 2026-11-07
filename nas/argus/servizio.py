"""Il servizio: tiene insieme motore, PC, visione, SemIf, voce, prese, coda delle foto e database.

Gira dentro il ciclo asyncio di FastAPI. Il motore lo tocca solo questo ciclo (niente thread):
la visione lavora nei suoi thread e passa i riassunti del minuto.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import httpx

from . import VERSIONE, testi
from .comandi import (CmdAiuto, CmdDormo, CmdErrore, CmdLavoro, CmdLista, CmdPausa, CmdRegistra, CmdStato,
                      analizza)
from .config import Config, carica
from .db import Database
from .diario import compatta, riga
from .lavori import CodaLavori
from .liste import Liste, Modifica
from .motore import (ChiediPausa, ChiediPensiero, Episodio, Evento, Mezzanotte, Minuto, MinutoClassificato,
                     Motore, QuotaFatta, Regole, SpegniPresa, Voce)
from .pc_attivita import MemoriaPc, categoria, chiave_verdetto, da_giudicare, riassumi
from .prese import Prese
from .semif import (NON_SI_CAPISCE, Decisore, DecisoreNonDisponibile, Domanda, domanda_pausa,
                    domanda_pensiero, domanda_titolo)
from .tempo import Orologio, hhmm, inizio_minuto, iso
from .visione import SorgenteVisione
from .voce import Voce as ServizioVoce

log = logging.getLogger("argus.servizio")

EVENTI_PC = {"agente_avviato", "agente_riaperto", "agente_chiuso", "agente_bloccato", "sblocco_emergenza",
             "pactum_copre", "nas_irraggiungibile"}
MAX_FOTO = 20
MAX_BYTE_FOTO = 8 * 1024 * 1024
MIN_FOTO_VALIDE = {"vs": 3}  # per lb, qd e tf l'oggetto deve esserci in almeno metà delle foto
VERDETTI_AL_PC = 300  # i più recenti, più quelli dei titoli visti negli ultimi 10 minuti
VERDETTI_VISTI_MINUTI = 10
NON_SI_CAPISCE_VALE = timedelta(minutes=15)  # poi il titolo si rigiudica (regole, sezione 9)


def token_pc(cartella: Path) -> str:
    """Il token del PC: 32 byte casuali in esadecimale, creato al primo avvio (contratto, sezione 1)."""
    return _segreto(Path(cartella) / "token-pc.txt")


def _segreto(percorso: Path) -> str:
    if percorso.exists():
        token = percorso.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{64}", token):
            return token
    percorso.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    percorso.write_text(token + "\n", encoding="utf-8")
    try:
        percorso.chmod(0o600)
    except OSError:
        pass
    log.info("Creato %s", percorso)
    return token


RE_SEGRETO_SBLOCCO = re.compile(r"[0-9a-fA-F]{64}")
FILE_SEGRETO_SBLOCCO = "token-sblocco.txt"


def _slug(nome: str) -> str:
    base = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or "senza-nome"


def tipo_immagine(dati: bytes) -> str | None:
    if dati[:3] == b"\xff\xd8\xff":
        return "jpg"
    if dati[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


@dataclass(order=True)
class _Decisione:
    priorita: int
    numero: int
    tipo: str = field(compare=False)
    stato: str = field(compare=False)
    domanda: Domanda = field(compare=False)
    al_risultato: Callable = field(compare=False)
    scade: datetime | None = field(compare=False, default=None)
    tentativi: int = field(compare=False, default=0)


class Servizio:
    def __init__(self, cartella_dati: Path | str, orologio: Orologio, config: Config | None = None,
                 client: httpx.AsyncClient | None = None, visione: SorgenteVisione | None = None,
                 crea_visione: Callable[["Servizio"], SorgenteVisione] | None = None,
                 attesa_decisore: float = 30.0):
        self.dati = Path(cartella_dati)
        self.dati.mkdir(parents=True, exist_ok=True)
        self.orologio = orologio
        self.config = config or carica(self.dati)
        self.db = Database(self.dati / "argus.db")
        self.token = token_pc(self.dati)
        # Il secondo segreto (sblocco d'emergenza) NON lo crea il NAS: lo genera l'installatore del PC
        # e lo registra una volta sola con POST /api/pc/registra-sblocco (contratto, sezione 1).
        self.client = client or httpx.AsyncClient()
        ora = orologio.adesso()
        regole = Regole(verifiche=self.config.verifiche, sabato_scuola=self.config.sabato_scuola,
                        patrono=self.config.patrono)
        salvato = self.db.leggi_stato("motore")
        if salvato:
            try:
                self.motore = Motore.importa(salvato, regole)
            except Exception:  # noqa: BLE001 - stato rovinato: si riparte, ma lo si scrive nel registro
                log.exception("Stato del motore illeggibile: riparto da zero")
                self.db.registra(ora, "stato_illeggibile", {})
                self.motore = Motore(regole, oggi=ora.date())
        else:
            self.motore = Motore(regole, oggi=ora.date())
        self.motore.inattivo = self.config.inattivo
        self.liste = Liste([Modifica.da_dict(d) for d in self.db.modifiche_liste()],
                           extra=self.config.liste_extra, versione_extra=self._versione_liste_extra())
        self.verdetti: dict[str, str] = self.db.verdetti()  # dal più vecchio al più recente
        self._ore_verdetti: dict[str, datetime] = self.db.ore_verdetti()
        self.pc = MemoriaPc()
        self.lavori = CodaLavori(self.db, self.dati / "lavori")
        self.decisore = Decisore(self.config.decisore_url, self.client, attesa_503=attesa_decisore)
        altoparlanti = {t.stanza: f"{t.id}_voce" for t in self.config.telecamere if t.altoparlante}
        self.voce = ServizioVoce(self.config.voci_url, self.config.voce, self.dati / "voce", self.client,
                                 self.config.go2rtc_url if altoparlanti else None, self.config.url_interno,
                                 altoparlanti)
        self.prese = Prese(self.config.home_assistant, self.config.home_assistant_token, self.config.prese,
                           self.client)
        self.visione = visione
        self._crea_visione = crea_visione
        self._coda: asyncio.PriorityQueue[_Decisione] | None = None
        self._numero = 0
        self._titoli_in_attesa: set[str] = set()
        self._compiti: set[asyncio.Task] = set()
        self._cicli: list[asyncio.Task] = []
        self._salute_servizi = {"decisore": "assente", "voci": "assente"}
        self.voci_dette: list[tuple[str, str, str]] = []  # (testo, stanza, dove) per prove e registro

    # ---- avvio e fermata ---------------------------------------------------------------------

    async def avvia(self, cicli: bool = True) -> None:
        self._coda = asyncio.PriorityQueue()
        if self.visione is None and not self.config.inattivo and self._crea_visione is not None:
            self.visione = self._crea_visione(self)
        if self.visione is not None:
            self.visione.imposta_contesto(self.motore.contesto_visione(self.orologio.adesso()))
            self.visione.avvia()
        self.db.registra(self.orologio.adesso(), "avvio", {"versione": VERSIONE,
                                                          "telecamere": [t.id for t in self.config.telecamere]})
        if cicli:
            self._cicli = [
                asyncio.create_task(self._ciclo_minuti(), name="minuti"),
                asyncio.create_task(self._ciclo_diario(), name="diario"),
                asyncio.create_task(self._lavoratore_decisioni(), name="decisioni"),
                asyncio.create_task(self._ciclo_salute(), name="salute"),
            ]
            self._lancia(self.voce.prepara_fisse())

    async def ferma(self) -> None:
        for c in self._cicli:
            c.cancel()
        for c in list(self._compiti):
            c.cancel()
        await asyncio.gather(*self._cicli, *self._compiti, return_exceptions=True)
        if self.visione is not None:
            self.visione.ferma()
        self._salva()
        self.db.chiudi()

    def _lancia(self, coro) -> asyncio.Task:
        compito = asyncio.create_task(coro)
        self._compiti.add(compito)
        compito.add_done_callback(self._compiti.discard)
        return compito

    async def attendi_compiti(self) -> None:
        """Per le prove: aspetta che voci, prese e simili abbiano finito."""
        while self._compiti:
            await asyncio.gather(*list(self._compiti), return_exceptions=True)

    # ---- cicli -------------------------------------------------------------------------------

    async def _ciclo_minuti(self) -> None:
        while True:
            ora = self.orologio.adesso()
            prossimo = inizio_minuto(ora) + timedelta(minutes=1, seconds=2)
            await asyncio.sleep(max(0.5, (prossimo - ora).total_seconds()))
            try:
                await self.passo_minuto(inizio_minuto(self.orologio.adesso()) - timedelta(minutes=1))
            except Exception:  # noqa: BLE001 - il ciclo non deve mai morire
                log.exception("Errore nel minuto")

    async def _ciclo_diario(self) -> None:
        while True:
            await asyncio.sleep(10)
            try:
                self.scrivi_diario()
            except Exception:  # noqa: BLE001
                log.exception("Errore nel diario")

    async def _ciclo_salute(self) -> None:
        while True:
            self._salute_servizi["decisore"] = await self.decisore.salute()
            try:
                # Il servizio delle voci risponde su /salute con {"ok": true, "motori": [...]}:
                # è "ok" solo se c'è anche la voce scelta in configurazione.
                r = await self.client.get(self.voce.voci_url + "/salute", timeout=3.0)
                corpo = r.json() if r.status_code == 200 else None
                buono = (isinstance(corpo, dict) and corpo.get("ok") is True
                         and self.voce.motore_voce in (corpo.get("motori") or []))
                self._salute_servizi["voci"] = "ok" if buono else "assente"
            except (httpx.HTTPError, ValueError):
                self._salute_servizi["voci"] = "assente"
            await asyncio.sleep(300)

    # ---- il minuto ---------------------------------------------------------------------------

    def costruisci_minuto(self, inizio: datetime) -> Minuto:
        if self.visione is not None:
            campi = dict(self.visione.minuto(inizio))
        else:
            campi = {"visto": False, "telecamere_ok": False}
        liste = self.liste.attive(inizio)
        campioni = self.pc.del_minuto_con_ora(inizio)
        pc = riassumi([d for _, d in campioni], liste, self.verdetti, ore=[q for q, _ in campioni])
        campi.pop("ora", None)
        campi.pop("pc", None)
        for chiave in ("in_mano", "schermi", "stanze_cieche"):
            if chiave in campi:
                campi[chiave] = frozenset(campi[chiave])
        return Minuto(ora=inizio, pc=pc, **campi)

    async def passo_minuto(self, inizio: datetime) -> list:
        inizio = inizio_minuto(inizio)
        effetti = self.motore.allinea(inizio)
        effetti += self.motore.tick(self.costruisci_minuto(inizio))
        await self.gestisci(effetti, inizio)
        self._salva()
        if self.visione is not None:
            self.visione.imposta_contesto(self.motore.contesto_visione(self.orologio.adesso()))
        return effetti

    def scrivi_diario(self) -> str | None:
        ora = self.orologio.adesso()
        if not self.motore.attivo(ora):
            return None
        scena = self.visione.scena(ora) if self.visione is not None else None
        campione = self.pc.ultimo_campione(ora)
        cat = categoria(campione, self.liste.attive(ora), self.verdetti) if campione else None
        g = self.motore.giorno
        testo = riga(ora, scena, campione, cat, self.motore.comando_attivo(ora),
                     g.pausa.motivo if g.pausa is not None else None)
        self.db.scrivi_diario(ora, testo)
        return testo

    async def gestisci(self, effetti: list, ora: datetime) -> None:
        for e in effetti:
            if isinstance(e, MinutoClassificato):
                self.db.salva_minuto(e.ora, e.classe.value, e.motivo, e.aggiunta)
            elif isinstance(e, Evento):
                self.db.registra(ora, e.tipo, e.dettagli)
            elif isinstance(e, Episodio):
                self.db.salva_episodio(e.tipo, e.inizio, e.fine, e.minuti, e.aggiunta, e.dettagli)
            elif isinstance(e, Voce):
                self._lancia(self._di(e.testo, e.stanza, e.motivo))
            elif isinstance(e, SpegniPresa):
                self._lancia(self._spegni(e.dispositivo, e.stanza))
            elif isinstance(e, ChiediPensiero):
                self._chiedi_pensiero(e)
            elif isinstance(e, ChiediPausa):
                self._chiedi_pausa(e)
            elif isinstance(e, QuotaFatta):
                if self.visione is not None:
                    self.visione.imposta_contesto(self.motore.contesto_visione(ora))
            elif isinstance(e, Mezzanotte):
                self.lavori.mezzanotte()
                self.db.pulisci_diario(ora)
                n = self.db.pulisci_verdetti(ora)
                if n:
                    self.verdetti = self.db.verdetti()
                    self._ore_verdetti = self.db.ore_verdetti()
        self._salva_giorno()

    async def _di(self, testo: str, stanza: str | None, motivo: str) -> None:
        ora = self.orologio.adesso()
        dove = await self.voce.dici(testo, stanza, ora)
        self.voci_dette.append((testo, stanza or "", dove))
        self.db.registra(ora, "voce", {"testo": testo, "stanza": stanza, "dove": dove, "motivo": motivo})

    async def _spegni(self, dispositivo: str, stanza: str | None) -> None:
        spente = await self.prese.spegni(dispositivo, stanza)
        if spente:
            self.db.registra(self.orologio.adesso(), "presa_spenta", {"dispositivo": dispositivo, "prese": spente})

    def _salva(self) -> None:
        self.db.scrivi_stato("motore", self.motore.esporta())

    def _salva_giorno(self) -> None:
        g = self.motore.giorno
        self.db.salva_giorno({
            "data": g.data.isoformat(), "scuola": int(g.scuola), "arrivo": iso(g.arrivo), "riporto": g.riporto,
            "verifiche": g.verifiche, "studio": g.studio, "lavoro": g.lavoro, "agg_distrazione": g.agg_distrazione,
            "agg_imbroglio": g.agg_imbroglio, "fatti": self.motore.fatti(), "totale": self.motore.totale(),
            "fatta_alle": iso(g.fatta_alle),
        })

    # ---- decisioni (SemIf) ---------------------------------------------------------------------

    def _metti_in_coda(self, priorita: int, tipo: str, stato: str, domanda: Domanda, al_risultato: Callable,
                       scade: datetime | None = None) -> None:
        if self._coda is None:
            self._coda = asyncio.PriorityQueue()
        self._numero += 1
        self._coda.put_nowait(_Decisione(priorita, self._numero, tipo, stato, domanda, al_risultato, scade))

    def _testo_diario(self, da: datetime, a: datetime) -> str:
        righe = compatta(self.db.diario(da, a))
        return "\n".join(righe) if righe else "(nessuna riga)"

    def _chiedi_pensiero(self, e: ChiediPensiero) -> None:
        prima = self._testo_diario(e.inizio - timedelta(minutes=15), e.inizio)
        durante = self._testo_diario(e.inizio, e.fine)
        dopo = self._testo_diario(e.fine, e.fine_dopo)
        stato = (f"Diario di prima (15 minuti):\n{prima}\n\nDiario durante il tempo fermo:\n{durante}\n\n"
                 f"Diario di dopo:\n{dopo}")
        domanda = domanda_pensiero(hhmm(e.inizio), hhmm(e.fine), e.minuti)
        fine_giorno = datetime.combine(e.inizio.date(), datetime.max.time(), tzinfo=e.inizio.tzinfo)

        async def al_risultato(esito: str) -> None:
            ora = self.orologio.adesso()
            await self.gestisci(self.motore.giudizio_pensiero(e.id, esito, ora), ora)
            self._salva()

        self._metti_in_coda(2, "pensiero", stato, domanda, al_risultato, scade=fine_giorno)

    def _chiedi_pausa(self, e: ChiediPausa) -> None:
        ora = self.orologio.adesso()
        stato = f"Diario dall'inizio della pausa ({hhmm(e.inizio)}):\n{self._testo_diario(e.inizio, ora + timedelta(seconds=1))}"

        async def al_risultato(esito: str) -> None:
            adesso = self.orologio.adesso()
            await self.gestisci(self.motore.esito_pausa(e.id, esito, adesso), adesso)
            self._salva()

        self._metti_in_coda(1, "pausa", stato, domanda_pausa(e.motivo), al_risultato,
                            scade=ora + timedelta(minutes=20))

    def _chiedi_titolo(self, dominio: str, titolo: str) -> None:
        chiave = chiave_verdetto(dominio, titolo)
        if chiave in self._titoli_in_attesa or chiave in self.verdetti:
            return
        self._titoli_in_attesa.add(chiave)
        stato = f"Pagina aperta sul computer dello studente. Sito: {dominio}. Titolo della pagina: «{titolo}»."

        async def al_risultato(esito: str | None) -> None:
            self._titoli_in_attesa.discard(chiave)
            if esito is None:
                return  # decisore irraggiungibile: si richiederà alla prossima occasione
            self._metti_verdetto(chiave, dominio, titolo, esito, self.orologio.adesso())

        self._metti_in_coda(0, "titolo", stato, domanda_titolo(dominio, titolo), al_risultato,
                            scade=self.orologio.adesso() + timedelta(minutes=10))

    async def esegui_decisione(self, d: _Decisione) -> str | None:
        """Una decisione: SemIf o, se è scaduta / irraggiungibile, nel dubbio."""
        ora = self.orologio.adesso()
        if d.scade is not None and ora > d.scade:
            esito = NON_SI_CAPISCE if d.tipo != "titolo" else None
            await _chiama(d.al_risultato, esito)
            return esito
        try:
            risposte = await self.decisore.decidi(d.stato, [d.domanda])
            esito = risposte.get(d.domanda.id, NON_SI_CAPISCE)
        except DecisoreNonDisponibile as err:
            log.warning("SemIf non disponibile (%s): %s", d.tipo, err)
            d.tentativi += 1
            if d.tipo != "titolo" and d.tentativi < 10 and self._coda is not None:
                async def riprova() -> None:
                    await asyncio.sleep(60)
                    self._coda.put_nowait(d)
                self._lancia(riprova())
                return None
            esito = NON_SI_CAPISCE if d.tipo != "titolo" else None
        self.db.registra(self.orologio.adesso(), "semif", {"tipo": d.tipo, "esito": esito})
        await _chiama(d.al_risultato, esito)
        return esito

    async def _lavoratore_decisioni(self) -> None:
        assert self._coda is not None
        while True:
            d = await self._coda.get()
            try:
                await self.esegui_decisione(d)
            except Exception:  # noqa: BLE001
                log.exception("Errore in una decisione")

    async def svuota_decisioni(self) -> int:
        """Per le prove: esegue subito tutte le decisioni in coda."""
        n = 0
        while self._coda is not None and not self._coda.empty():
            await self.esegui_decisione(self._coda.get_nowait())
            n += 1
        return n

    # ---- quello che chiede il PC -------------------------------------------------------------

    async def _allinea(self) -> datetime:
        ora = self.orologio.adesso()
        effetti = self.motore.allinea(ora)
        if effetti:
            await self.gestisci(effetti, ora)
            self._salva()
        return ora

    async def stato_pc(self) -> dict:
        ora = await self._allinea()
        self._scadi_verdetti(ora)
        base = self.motore.stato_pc(ora)
        risposta = {
            "ora_server": iso(ora),
            "modalita": base["modalita"],
            "liste_versione": self.liste.versione(ora),
            "quota": base["quota"],
            "classe_adesso": base["classe_adesso"],
            "comando_attivo": base["comando_attivo"],
            "verdetti": self._verdetti_per_pc(ora),
            "messaggio_copertura": base["messaggio_copertura"],
            "sblocco_fino": iso(self.motore.s.sblocco_fino) if self.motore.sblocco_attivo(ora) else None,
            "quota_fatta_oggi": base["quota_fatta_oggi"],
        }
        di_voce = self.voce.di_voce(ora)
        if di_voce:
            risposta["di_voce"] = di_voce
        return risposta

    def liste_pc(self) -> dict:
        return self.liste.per_pc(self.orologio.adesso())

    def ricevi_attivita(self, campioni: list[dict]) -> None:
        ora = self.orologio.adesso()
        self.pc.aggiungi(campioni, ora)
        # I titoli vanno a SemIf solo mentre la quota è in corso: in libero o inattivo no.
        if self.motore.modalita(ora) not in ("studio", "lavoro"):
            return
        self._scadi_verdetti(ora)
        for dominio, titolo in da_giudicare(campioni, self.liste.attive(ora), self.verdetti):
            self._chiedi_titolo(dominio, titolo)

    # ---- verdetti sui titoli -----------------------------------------------------------------

    def _metti_verdetto(self, chiave: str, dominio: str, titolo: str, esito: str, ora: datetime) -> None:
        self.verdetti.pop(chiave, None)
        self.verdetti[chiave] = esito  # in fondo: è il più recente
        self._ore_verdetti[chiave] = ora
        self.db.salva_verdetto(chiave, dominio, titolo, esito, ora)

    def _scadi_verdetti(self, ora: datetime) -> None:
        """`non_si_capisce` vale 15 minuti, poi il titolo si rigiudica."""
        for chiave, esito in list(self.verdetti.items()):
            quando = self._ore_verdetti.get(chiave)
            if esito == "non_si_capisce" and quando is not None and ora - quando > NON_SI_CAPISCE_VALE:
                del self.verdetti[chiave]
                self._ore_verdetti.pop(chiave, None)
                self.db.togli_verdetto(chiave)

    def _verdetti_per_pc(self, ora: datetime) -> dict[str, str]:
        """I 300 più recenti, più SEMPRE quelli dei titoli visti negli ultimi 10 minuti."""
        scelti = dict(list(self.verdetti.items())[-VERDETTI_AL_PC:])
        for chiave in self.pc.chiavi_recenti(ora, VERDETTI_VISTI_MINUTI):
            if chiave in self.verdetti:
                scelti[chiave] = self.verdetti[chiave]
        return scelti

    def _versione_liste_extra(self) -> int:
        """Sale di uno ogni volta che `liste_extra` in config.json cambia (il PC rilegge le liste)."""
        impronta = hashlib.sha1(json.dumps(self.config.liste_extra, sort_keys=True,
                                           ensure_ascii=False).encode("utf-8")).hexdigest()
        salvato = self.db.leggi_stato("liste_extra") or {}
        versione = int(salvato.get("versione", 0))
        if salvato.get("impronta") != impronta:
            if salvato or self.config.liste_extra:
                versione += 1
            self.db.scrivi_stato("liste_extra", {"impronta": impronta, "versione": versione})
        return versione

    async def comando(self, testo: str) -> dict:
        ora = await self._allinea()
        cmd = analizza(testo)
        self.db.registra(ora, "comando", {"testo": testo[:200]})
        if isinstance(cmd, (CmdPausa, CmdLavoro, CmdDormo, CmdStato, CmdErrore)):
            r = self.motore.comando(cmd, ora)
            await self.gestisci(r.effetti, ora)
            self._salva()
            if self.visione is not None:
                self.visione.imposta_contesto(self.motore.contesto_visione(ora))
            return {"ok": r.ok, "risposta": r.risposta, "chiede_foto": None}
        if isinstance(cmd, CmdAiuto):
            return {"ok": True, "risposta": testi.AIUTO, "chiede_foto": None}
        if isinstance(cmd, CmdLista):
            if cmd.azione == "ag":
                ok, risposta, modifica = self.liste.aggiungi(cmd.lista, cmd.voce, ora)
            else:
                ok, risposta, modifica = self.liste.togli(cmd.lista, cmd.voce, ora)
            for m in self.liste.modifiche:
                self.db.salva_modifica_lista(m.a_dict())
            if modifica is not None:
                self.db.registra(ora, "lista", modifica.a_dict())
            return {"ok": ok, "risposta": risposta, "chiede_foto": None}
        assert isinstance(cmd, CmdRegistra)
        if cmd.azione == "elenco":
            nomi = self.db.nomi_registrati(cmd.tipo)
            risposta = testi.ELENCO[cmd.tipo].format(nomi=", ".join(nomi)) if nomi else testi.ELENCO_VUOTO[cmd.tipo]
            return {"ok": True, "risposta": risposta, "chiede_foto": None}
        if cmd.azione == "togli":
            presenti = [n.lower() for n in self.db.nomi_registrati(cmd.tipo)]
            if cmd.nome.lower() not in presenti:
                return {"ok": True, "risposta": testi.NON_TROVATO.format(nome=cmd.nome), "chiede_foto": None}
            self.db.togli_registrato(cmd.tipo, cmd.nome)
            self._cancella_cartella_registrati(cmd.tipo, cmd.nome)
            self.db.registra(ora, "registrato_tolto", {"tipo": cmd.tipo, "nome": cmd.nome})
            if self.visione is not None:
                self.visione.ricarica_registrati()
            return {"ok": True, "risposta": testi.TOLTO.format(nome=cmd.nome), "chiede_foto": None}
        chiede_foto = {"tipo": cmd.tipo, "nome": cmd.nome, "scatti": testi.FOTO_SCATTI[cmd.tipo],
                       "consiglio": testi.FOTO_CONSIGLIO[cmd.tipo]}
        risposta = testi.REGISTRA_PRONTO[cmd.tipo].format(nome=cmd.nome or "")
        return {"ok": True, "risposta": risposta, "chiede_foto": chiede_foto}

    def _cartella_registrati(self, tipo: str, nome: str | None) -> Path:
        return self.dati / "registrati" / tipo / (_slug(nome) if nome else tipo)

    def _cancella_cartella_registrati(self, tipo: str, nome: str | None) -> None:
        cartella = self._cartella_registrati(tipo, nome)
        if cartella.exists():
            shutil.rmtree(cartella, ignore_errors=True)

    async def foto(self, tipo: str, nome: str | None, immagini: list[bytes]) -> tuple[bool, str]:
        ora = self.orologio.adesso()
        if tipo not in ("lb", "qd", "vs", "tf"):
            return False, "Tipo non valido: deve essere lb, qd, vs o tf."
        if tipo in ("lb", "qd"):
            nome = " ".join((nome or "").split())
            if not nome or len(nome) > 40:
                return False, "Manca il nome (per esempio: storia)."
        else:
            nome = None
        if not 1 <= len(immagini) <= MAX_FOTO:
            return False, "Servono da 1 a 20 foto."
        for dati in immagini:
            if len(dati) > MAX_BYTE_FOTO:
                return False, "Una foto è più grande di 8 MB."
            if tipo_immagine(dati) is None:
                return False, "Le foto devono essere JPEG o PNG."
        modello, vettori = (None, [None] * len(immagini))
        if self.visione is not None:
            modello, vettori = await asyncio.to_thread(self.visione.registra, tipo, immagini)
        if self.visione is not None and modello is not None:
            validi = sum(1 for v in vettori if v is not None)
            if tipo == "vs":
                minimo = min(MIN_FOTO_VALIDE[tipo], len(immagini))
                if validi == 0:
                    return False, testi.FOTO_NESSUN_VISO
                if validi < minimo:
                    return False, testi.FOTO_POCHE_VALIDE.format(validi=validi, n=len(immagini), minimo=minimo)
            elif validi * 2 < len(immagini):
                # libro, quaderno o telefono: deve esserci in almeno metà delle foto
                return False, testi.FOTO_OGGETTO_MANCA[tipo]
        # Una registrazione nuova sostituisce la vecchia con lo stesso nome (o il viso / telefono).
        if tipo in ("vs", "tf"):
            self.db.togli_tipo(tipo)
        else:
            self.db.togli_registrato(tipo, nome)
        self._cancella_cartella_registrati(tipo, nome)
        cartella = self._cartella_registrati(tipo, nome)
        cartella.mkdir(parents=True, exist_ok=True)
        marca = ora.strftime("%Y%m%d-%H%M%S")
        for i, (dati, vettore) in enumerate(zip(immagini, vettori), start=1):
            file = cartella / f"{marca}-{i:02d}.{tipo_immagine(dati)}"
            file.write_bytes(dati)
            self.db.salva_vettore(tipo, nome or tipo, modello, vettore, str(file), ora)
        if self.visione is not None:
            self.visione.ricarica_registrati()
        self.db.registra(ora, "registrato", {"tipo": tipo, "nome": nome, "foto": len(immagini)})
        if tipo == "vs":
            return True, testi.FOTO_VISO_SALVATE.format(n=len(immagini))
        if tipo == "tf":
            return True, testi.FOTO_TELEFONO_SALVATE.format(n=len(immagini))
        return True, testi.FOTO_SALVATE.format(nome=nome, n=len(immagini))

    def prossimo_lavoro(self) -> dict | None:
        return self.lavori.prossimo(self.orologio.adesso())

    def rispondi_lavoro(self, id_lavoro: str, risposte: dict, millisecondi: int | None, modello: str | None) -> dict:
        return self.lavori.rispondi(id_lavoro, risposte, millisecondi, modello, self.orologio.adesso())

    # ---- secondo segreto per lo sblocco d'emergenza -------------------------------------------

    def segreto_sblocco(self) -> str | None:
        """Il segreto registrato dall'installatore del PC, o None se non c'è (nessuno sblocco possibile)."""
        percorso = self.dati / FILE_SEGRETO_SBLOCCO
        try:
            segreto = percorso.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return segreto if RE_SEGRETO_SBLOCCO.fullmatch(segreto) else None

    def registra_sblocco(self, segreto: str) -> bool:
        """Salva il segreto solo se sul NAS non ce n'è già uno. Falso = già registrato (si azzera a mano
        cancellando /data/token-sblocco.txt). Il segreto non finisce mai nel registro."""
        percorso = self.dati / FILE_SEGRETO_SBLOCCO
        if percorso.exists() and percorso.read_text(encoding="utf-8").strip():
            self.db.registra(self.orologio.adesso(), "sblocco_registrazione_rifiutata", {"motivo": "già registrato"})
            return False
        percorso.write_text(segreto + "\n", encoding="utf-8")
        try:
            percorso.chmod(0o600)
        except OSError:
            pass
        self.db.registra(self.orologio.adesso(), "sblocco_registrato", {})
        log.info("Registrato il segreto dello sblocco in %s", percorso)
        return True

    async def evento_pc(self, tipo: str, dettagli: dict, ts: str | None) -> None:
        """Il segreto dello sblocco e le ore (intero 0-48) li controlla api.py prima di arrivare qui."""
        ora = await self._allinea()
        self.db.registra(ora, "pc_" + tipo, {"dettagli": dettagli, "ts_pc": ts})
        if tipo == "sblocco_emergenza":
            ore = int(dettagli["ore"])
            # Calcolato con l'orologio del NAS: un eventuale "fino" mandato dal PC non conta.
            fino = ora + timedelta(hours=ore) if ore > 0 else None
            await self.gestisci(self.motore.sblocco(fino, ora), ora)
            self._salva()

    def salute(self) -> dict:
        telecamere = {t.id: "assente" for t in self.config.telecamere}
        if self.visione is not None:
            telecamere.update(self.visione.telecamere())
        decisore = "ok" if self.decisore.ultimo_ok else self._salute_servizi["decisore"]
        voci = "ok" if self.voce.ultimo_ok else self._salute_servizi["voci"]
        return {"ok": True, "versione": VERSIONE, "telecamere": telecamere, "decisore": decisore, "voci": voci}


async def _chiama(funzione: Callable, valore) -> None:
    risultato = funzione(valore)
    if asyncio.iscoroutine(risultato):
        await risultato

