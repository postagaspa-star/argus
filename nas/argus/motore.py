"""Il motore delle regole (docs/regole.md). È il cuore di Argus.

Puro: niente rete, niente disco, niente orologio. Chi lo usa gli passa:
- un `Minuto` alla volta (cosa hanno visto le telecamere e cosa diceva il PC in quel minuto);
- i comandi del terminale con l'ora in cui sono arrivati;
- i giudizi di SemIf quando arrivano.
Lui risponde con una lista di "effetti" (frasi da dire, righe di registro, domande da fare a
SemIf, prese da spegnere...) che il servizio esegue.

Principio fisso (regole, sezione 4): nel dubbio, né avanti né punizione.
Le letture delle regole che non erano scritte esplicitamente sono spiegate in NOTE-COSTRUTTORE.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum

from . import testi
from .calendario import giorno_di_scuola
from .comandi import CmdDormo, CmdErrore, CmdLavoro, CmdPausa, CmdStato, Comando
from .serial import a_dict, da_dict
from .tempo import FUSO, arrotonda_su_minuto, hhmm, inizio_minuto, minuti_interi_su

# --- Numeri delle regole -----------------------------------------------------------------------
QUOTA_BASE = 60
RIPORTO_MAX = 30
TETTO_DISTRAZIONI = 60
AGGIUNTA_IMBROGLIO = 30
TETTO_AGGIUNTE = 120
ORA_MINIMA_ARRIVO = time(11, 0)
ASSENZA_PER_ARRIVO = timedelta(hours=3)
PRANZO_ENTRO = timedelta(minutes=30)
PRANZO_DURATA_MAX = 60
FUORI_VISTA_NEUTRI = 5
PAUSA_INIZIALE = 10
PAUSA_OGNI = 50
PAUSA_AGGIUNTA = 10
DM_CONFERMA = timedelta(minutes=5)
SOSPESO_MAX_STUDIO = 10
SOSPESO_FINESTRA_DOPO = timedelta(minutes=30)
VOCE_OGNI = timedelta(minutes=2)
IMBROGLIO_FINE_DOPO = 5  # minuti senza prova per chiudere un episodio di imbroglio
DISTRAZIONE_FINE_DOPO = 5  # minuti senza distrazione per chiudere un episodio (regole, sezione 5)
PAUSA_CONTROLLO_DOPO = 2  # minuti visto durante la pausa prima di chiedere a SemIf
PAUSA_CONTROLLO_OGNI = timedelta(minutes=5)

OGGETTI_STUDIO = frozenset({"libro_scuola", "quaderno_scuola"})
TELEFONI_SUOI = frozenset({"telefono_suo", "telefono"})
DISPOSITIVI_IMBROGLIO_IN_MANO = frozenset({"telefono_altro", "tablet"})
LETTURE_ALTRE = frozenset({"libro_altro", "libro_dubbio"})


class Classe(str, Enum):
    STUDIO = "studio"
    LAVORO = "lavoro"
    NEUTRO = "neutro"
    DISTRAZIONE = "distrazione"
    IMBROGLIO = "imbroglio"
    SOSPESO = "sospeso"
    NESSUNA = "nessuna"


# --- Ingressi ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class PcMinuto:
    """Il PC in un minuto, già riassunto (vedi pc_attivita.py).

    categoria: studio | lavoro | sempre | svago | attesa | dubbio | coperto | pactum | bloccato
               | mai | altro | nessuna
    """

    categoria: str = "nessuna"
    in_uso: bool = False  # tasti o mouse negli ultimi 5 minuti (leggere un PDF è ancora "in uso")
    audio_studio: bool = False  # audio della voce di Lectio
    ultimo_input: datetime | None = None  # quando è stato toccato l'ultima volta (stima del NAS)


@dataclass(frozen=True)
class Minuto:
    """Quello che si sa di un minuto. Tutti i campi "visti" sono già filtrati dalla visione:
    qui arrivano solo cose chiare (un telefono è in `in_mano` solo se acceso, eccetera)."""

    ora: datetime
    telecamere_ok: bool = True  # falso se tutte le telecamere sono giù o la visione è ferma
    stanze_cieche: frozenset[str] = frozenset()  # stanze con la telecamera giù o ferma da più di 30 s
    visto: bool = False  # lo studente riconosciuto (o la persona sdraiata durante un dm)
    forse_visto: bool = False  # persona non riconosciuta sdraiata nel letto della sua stanza
    stanza: str | None = None
    dove: str | None = None  # scrivania | divano | letto | in_piedi
    posa: str | None = None  # seduto | sdraiato | in_piedi | chino
    in_mano: frozenset[str] = frozenset()
    schermi: frozenset[str] = frozenset()  # schermi non controllati accesi davanti: tv, tablet, telefono_altro, console
    scrive: bool = False
    mangia: bool = False
    dorme: bool = False
    pensiero: bool = False  # fermo, niente in mano, occhi aperti
    pc: PcMinuto | None = None


# --- Effetti -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Voce:
    testo: str
    stanza: str | None
    motivo: str


@dataclass(frozen=True)
class Evento:
    tipo: str
    dettagli: dict


@dataclass(frozen=True)
class MinutoClassificato:
    ora: datetime
    classe: Classe
    motivo: str
    aggiunta: int


@dataclass(frozen=True)
class Episodio:
    tipo: str  # distrazione | imbroglio | pausa | dm | lv | sospeso | pranzo
    inizio: datetime
    fine: datetime
    minuti: int
    aggiunta: int
    dettagli: dict


@dataclass(frozen=True)
class ChiediPensiero:
    id: str
    inizio: datetime
    fine: datetime
    fine_dopo: datetime
    minuti: int


@dataclass(frozen=True)
class ChiediPausa:
    id: str
    motivo: str
    inizio: datetime


@dataclass(frozen=True)
class SpegniPresa:
    dispositivo: str
    stanza: str | None


@dataclass(frozen=True)
class QuotaFatta:
    ora: datetime


@dataclass(frozen=True)
class Mezzanotte:
    giorno_chiuso: date


@dataclass(frozen=True)
class Risposta:
    ok: bool
    risposta: str
    effetti: list


# --- Stato -------------------------------------------------------------------------------------

@dataclass
class Regole:
    base: int = QUOTA_BASE
    verifiche: int = 0  # Classe Viva e WhatsApp sono in stand-by: 0
    sabato_scuola: bool = False
    patrono: str | None = None


@dataclass
class Pausa:
    id: str
    inizio: datetime
    fine: datetime
    motivo: str
    minuti: int
    minuti_visto: int = 0
    ultimo_controllo: datetime | None = None
    falsa: bool = False


@dataclass
class Lavoro:
    inizio: datetime
    fine: datetime


@dataclass
class Dormo:
    inizio: datetime
    fine: datetime
    stato: str = "attesa"  # attesa | valido
    stanza: str | None = None
    dove: str | None = None
    confermato: datetime | None = None  # fine del minuto in cui è stato visto sdraiato
    sforato: bool = False  # scaduto ma ancora sdraiato: resta lui finché non si alza


@dataclass
class EpisodioDistrazione:
    inizio: datetime
    motivo: str
    minuti: int = 0
    aggiunta: int = 0
    ultimo_distratto: datetime | None = None
    senza: int = 0  # minuti di fila senza distrazione


@dataclass
class EpisodioImbroglio:
    inizio: datetime
    motivo: str
    dispositivo: str
    aggiunta: int
    minuti: int = 1
    senza: int = 0


@dataclass
class Sospeso:
    id: str
    inizio: datetime
    minuti: int = 0
    fine: datetime | None = None
    scadenza: datetime | None = None
    dopo: int = 0
    stato: str = "in_corso"  # in_corso | dopo | da_giudicare | studio | neutro
    credito: int = 0


@dataclass
class Giorno:
    data: date
    scuola: bool
    base: int = QUOTA_BASE
    verifiche: int = 0
    riporto: int = 0
    arrivo: datetime | None = None
    studio: int = 0
    lavoro: int = 0
    agg_distrazione: int = 0
    agg_imbroglio: int = 0
    fatta_alle: datetime | None = None
    visto_mangiare: bool = False
    pranzo: str = "disponibile"  # disponibile | in_corso | usata | persa
    pranzo_inizio: datetime | None = None
    pranzo_minuti: int = 0
    pausa_usata: int = 0
    pausa: Pausa | None = None
    ultima_pausa: Pausa | None = None
    pausa_sforata: bool = False
    lv: Lavoro | None = None
    dm: Dormo | None = None
    fuori_vista: int = 0
    distrazione: EpisodioDistrazione | None = None
    imbroglio: EpisodioImbroglio | None = None
    sospesi: list[Sospeso] = field(default_factory=list)
    classe_ultima: str = "nessuna"
    ultimo_minuto: datetime | None = None
    conteggio: dict[str, int] = field(default_factory=dict)


@dataclass
class StatoMotore:
    giorno: Giorno
    ultimo_visto: datetime | None = None
    ultimo_forse_visto: datetime | None = None
    ultima_stanza: str | None = None
    riporto_in_attesa: int = 0
    ultima_voce: datetime | None = None
    voce_in_attesa: str | None = None
    sblocco_fino: datetime | None = None
    contatore: int = 0


# --- Motore ------------------------------------------------------------------------------------

class Motore:
    def __init__(self, regole: Regole | None = None, stato: StatoMotore | None = None,
                 oggi: date | None = None):
        self.regole = regole or Regole()
        self.inattivo = False  # vero se non ci sono telecamere configurate
        self._distrazione_toccata = False  # il minuto in corso è passato da _distrazione?
        if stato is None:
            if oggi is None:
                raise ValueError("serve il giorno di partenza")
            stato = StatoMotore(giorno=Giorno(data=oggi, scuola=False))
            self.s = stato
            self.s.giorno = self._nuovo_giorno(oggi)
        else:
            self.s = stato

    # ---- salvataggio -------------------------------------------------------------------------

    def esporta(self) -> dict:
        return a_dict(self.s)

    @classmethod
    def importa(cls, dati: dict, regole: Regole | None = None) -> "Motore":
        return cls(regole=regole, stato=da_dict(StatoMotore, dati))

    # ---- numeri della quota ------------------------------------------------------------------

    @property
    def giorno(self) -> Giorno:
        return self.s.giorno

    def aggiunte(self) -> int:
        g = self.s.giorno
        return g.agg_distrazione + g.agg_imbroglio

    def totale(self) -> int:
        g = self.s.giorno
        return g.base + g.verifiche + g.riporto + self.aggiunte()

    def fatti(self) -> int:
        g = self.s.giorno
        tot = self.totale()
        # Il lavoro conta per tutto tranne i minuti delle verifiche (regole, sezione 3).
        return min(tot, g.studio + min(g.lavoro, max(0, tot - g.verifiche)))

    def mancano(self) -> int:
        return max(0, self.totale() - self.fatti())

    def sospeso(self) -> int:
        return sum(s.minuti for s in self.s.giorno.sospesi if s.stato in ("in_corso", "dopo", "da_giudicare"))

    def pausa_disponibile(self, ora: datetime) -> int:
        g = self.s.giorno
        if g.arrivo is None:
            return 0
        trascorsi = max(0.0, (ora - g.arrivo).total_seconds() / 60.0)
        budget = PAUSA_INIZIALE + PAUSA_AGGIUNTA * int(math.floor(trascorsi / PAUSA_OGNI))
        return max(0, budget - g.pausa_usata)

    # ---- stato del giorno --------------------------------------------------------------------

    def attivo(self, ora: datetime | None = None) -> bool:
        g = self.s.giorno
        return (not self.inattivo) and g.scuola and g.arrivo is not None and g.fatta_alle is None

    def sblocco_attivo(self, ora: datetime) -> bool:
        return self.s.sblocco_fino is not None and ora < self.s.sblocco_fino

    def analizza_immagini(self, ora: datetime) -> bool:
        """La visione gira solo nei giorni di scuola finché la quota non è fatta (regole, sezione 2)."""
        g = self.s.giorno
        return (not self.inattivo) and g.scuola and g.fatta_alle is None

    def modalita(self, ora: datetime) -> str:
        if self.inattivo:
            return "inattivo"
        if self.sblocco_attivo(ora):
            return "libero"
        if not self.attivo(ora):
            return "libero"
        g = self.s.giorno
        if g.lv is not None and ora < g.lv.fine:
            return "lavoro"
        return "studio"

    def comando_attivo(self, ora: datetime) -> dict | None:
        g = self.s.giorno
        if not self.attivo(ora):
            return None
        if g.pausa is not None and ora < g.pausa.fine:
            return {"tipo": "ps", "fino": hhmm(g.pausa.fine)}
        if g.dm is not None and ora < g.dm.fine:
            return {"tipo": "dm", "fino": hhmm(g.dm.fine)}
        if g.lv is not None and ora < g.lv.fine:
            return {"tipo": "lv", "fino": hhmm(g.lv.fine)}
        return None

    def classe_adesso(self, ora: datetime) -> str:
        g = self.s.giorno
        if not self.attivo(ora) or g.ultimo_minuto is None:
            return Classe.NESSUNA.value
        if ora - g.ultimo_minuto > timedelta(minutes=2, seconds=30):
            return Classe.NESSUNA.value
        return g.classe_ultima

    def contesto_visione(self, ora: datetime) -> dict:
        """Quello che la visione deve sapere: c'è un dm? (la persona sdraiata vale come lo studente)."""
        g = self.s.giorno
        # Anche dopo lo scadere (dm sforato) la persona sdraiata nello stesso posto resta lo studente.
        dm = g.dm if (g.dm is not None and self.attivo(ora)) else None
        return {
            "analizza": self.analizza_immagini(ora),
            "attivo": self.attivo(ora),
            "dm": dm.stato if dm else None,
            "dm_stanza": dm.stanza if dm else None,
            "dm_dove": dm.dove if dm else None,
            "pausa": g.pausa.motivo if g.pausa is not None else None,
            "lv": g.lv is not None,
        }

    def stato_pc(self, ora: datetime) -> dict:
        """Per GET /api/pc/stato. Chi chiama fa prima `allinea(ora)` e gestisce i suoi effetti."""
        g = self.s.giorno
        attivo = self.attivo(ora)
        mancano = self.mancano()
        fine = None
        if attivo:
            fine = hhmm(inizio_minuto(ora) + timedelta(minutes=mancano))
        return {
            "modalita": self.modalita(ora),
            "quota": {
                "fatti": self.fatti(),
                "totale": self.totale(),
                "sospeso": self.sospeso(),
                "aggiunte": self.aggiunte(),
                "pausa_disponibile": self.pausa_disponibile(ora) if attivo else 0,
                "fine_prevista": fine,
            },
            "classe_adesso": self.classe_adesso(ora),
            "comando_attivo": self.comando_attivo(ora),
            "messaggio_copertura": testi.mancano(mancano) if attivo else None,
            "quota_fatta_oggi": g.fatta_alle is not None,
        }

    def stato_testo(self, ora: datetime) -> str:
        """Risposta al comando `st`."""
        g = self.s.giorno
        if self.inattivo:
            return "Argus adesso è spento: niente quota."
        if self.sblocco_attivo(ora):
            return f"Sblocco d'emergenza fino alle {hhmm(self.s.sblocco_fino)}."
        if not g.scuola:
            return "Oggi non è giorno di scuola: sei libero."
        if g.arrivo is None:
            extra = f" Oggi ci sono {g.riporto} minuti portati da ieri." if g.riporto else ""
            return "La quota di oggi non è ancora partita: parte quando arrivi a casa." + extra
        if g.fatta_alle is not None:
            return f"Fatto per oggi: {self.fatti()} di {self.totale()} minuti. Sei libero."
        cmd = self.comando_attivo(ora)
        nomi = {"ps": "pausa", "dm": "dormo", "lv": "lavoro"}
        cmd_testo = f"{nomi[cmd['tipo']]} fino alle {cmd['fino']}" if cmd else "nessuno"
        stato = self.stato_pc(ora)
        q = stato["quota"]
        righe = [
            f"Quota: {q['fatti']} di {q['totale']} minuti (mancano {self.mancano()}).",
            f"In sospeso: {q['sospeso']} minuti.",
            f"Aggiunte di oggi: {q['aggiunte']} minuti.",
            f"Pausa disponibile: {q['pausa_disponibile']} minuti.",
            f"Adesso: {testi.CLASSI_PAROLE.get(stato['classe_adesso'], stato['classe_adesso'])}.",
            f"Comando attivo: {cmd_testo}.",
            f"Fine prevista: {q['fine_prevista']}.",
        ]
        return "\n".join(righe)

    # ---- giorni e mezzanotte -----------------------------------------------------------------

    def _nuovo_giorno(self, giorno: date) -> Giorno:
        scuola = giorno_di_scuola(giorno, self.regole.sabato_scuola, self.regole.patrono)
        riporto = 0
        if scuola:
            riporto = min(RIPORTO_MAX, self.s.riporto_in_attesa)
            self.s.riporto_in_attesa = 0
        return Giorno(data=giorno, scuola=scuola, base=self.regole.base,
                      verifiche=self.regole.verifiche if scuola else 0, riporto=riporto)

    def allinea(self, ora: datetime) -> list:
        """Se è cambiato il giorno, chiude quelli passati (anche più d'uno, se il NAS era spento)."""
        effetti: list = []
        while ora.date() > self.s.giorno.data:
            effetti += self._mezzanotte()
        return effetti

    def _mezzanotte(self) -> list:
        g = self.s.giorno
        mezzanotte = datetime.combine(g.data + timedelta(days=1), time(0, 0), tzinfo=FUSO)
        eff: list = []
        self._chiudi_tutto(mezzanotte, eff, perche="mezzanotte")
        for s in g.sospesi:
            if s.stato in ("in_corso", "dopo", "da_giudicare"):
                s.stato = "neutro"
                eff.append(Evento("sospeso_neutro", {"id": s.id, "minuti": s.minuti,
                                                      "perche": "giudizio non arrivato entro mezzanotte"}))
        if g.scuola and g.arrivo is not None and g.fatta_alle is None:
            mancavano = self.mancano()
            riporto = min(RIPORTO_MAX, mancavano)
            self.s.riporto_in_attesa = riporto
            eff.append(Evento("mezzanotte", {"giorno": g.data.isoformat(), "mancavano": mancavano,
                                             "riporto": riporto, "persi": mancavano - riporto,
                                             "fatti": self.fatti(), "totale": self.totale()}))
        elif g.scuola and g.arrivo is None:
            if g.riporto:
                eff.append(Evento("riporto_perso", {"giorno": g.data.isoformat(), "minuti": g.riporto,
                                                    "perche": "nessun arrivo"}))
            eff.append(Evento("mezzanotte", {"giorno": g.data.isoformat(), "arrivo": None}))
        else:
            eff.append(Evento("mezzanotte", {"giorno": g.data.isoformat(), "scuola": g.scuola,
                                             "fatta": g.fatta_alle is not None}))
        eff.append(Mezzanotte(g.data))
        self.s.giorno = self._nuovo_giorno(g.data + timedelta(days=1))
        self.s.voce_in_attesa = None
        return eff

    def _chiudi_tutto(self, ora: datetime, eff: list, perche: str) -> None:
        g = self.s.giorno
        if g.pausa is not None:
            self._chiudi_pausa(ora, eff, perche)
        if g.lv is not None:
            eff.append(Episodio("lv", g.lv.inizio, min(ora, g.lv.fine), minuti_interi_su(g.lv.inizio, min(ora, g.lv.fine)), 0, {"perche": perche}))
            g.lv = None
        if g.dm is not None:
            self._chiudi_dm(ora, eff, perche)
        self._chiudi_distrazione(ora, eff)
        self._chiudi_imbroglio(ora, eff)
        g.pausa_sforata = False
        for s in g.sospesi:
            if s.stato == "in_corso":
                s.fine = ora
                s.stato = "neutro"
                eff.append(Episodio("sospeso", s.inizio, ora, s.minuti, 0, {"esito": "neutro", "perche": perche}))

    # ---- comandi -----------------------------------------------------------------------------

    def comando(self, cmd: Comando, ora: datetime) -> Risposta:
        eff = self.allinea(ora)
        if isinstance(cmd, CmdErrore):
            return Risposta(False, cmd.risposta, eff)
        if isinstance(cmd, CmdStato):
            return Risposta(True, self.stato_testo(ora), eff)
        if not isinstance(cmd, (CmdPausa, CmdLavoro, CmdDormo)):
            raise TypeError(f"comando non del motore: {cmd!r}")
        if self.inattivo:
            return Risposta(True, testi.NON_SERVE_INATTIVO, eff)
        if not self.attivo(ora):
            return Risposta(True, testi.NON_SERVE_LIBERO, eff)
        g = self.s.giorno
        if isinstance(cmd, CmdPausa):
            # Una pausa nuova sostituisce quella in corso: i minuti non usati di quella contano come
            # disponibili, ma la si chiude solo se la nuova è accettata.
            disponibile = self.pausa_disponibile(ora)
            if g.pausa is not None:
                disponibile += g.pausa.minuti - self._minuti_usati(g.pausa, ora)
            if cmd.minuti > disponibile:
                if g.pausa is not None:
                    return Risposta(True, testi.budget_pausa(disponibile, resta_fino=hhmm(g.pausa.fine)), eff)
                return Risposta(True, testi.budget_pausa(disponibile), eff)
            if g.pausa is not None:
                self._chiudi_pausa(ora, eff, "sostituita da una pausa nuova")
            fine = arrotonda_su_minuto(ora + timedelta(minutes=cmd.minuti))
            g.pausa = Pausa(id=self._nuovo_id("p"), inizio=ora, fine=fine, motivo=cmd.motivo,
                            minuti=cmd.minuti)
            g.pausa_usata += cmd.minuti
            g.pausa_sforata = False
            g.fuori_vista = 0
            if g.dm is not None:
                self._chiudi_dm(ora, eff, "pausa")
            eff.append(Evento("pausa", {"motivo": cmd.motivo, "minuti": cmd.minuti, "fino": hhmm(fine)}))
            return Risposta(True, testi.PAUSA_OK.format(fino=hhmm(fine)), eff)
        if isinstance(cmd, CmdLavoro):
            if cmd.minuti == 0:
                if g.lv is None:
                    return Risposta(True, testi.LAVORO_NESSUNO, eff)
                eff.append(Episodio("lv", g.lv.inizio, ora, minuti_interi_su(g.lv.inizio, ora), 0, {"perche": "lv0"}))
                g.lv = None
                eff.append(Evento("lavoro_chiuso", {}))
                return Risposta(True, testi.LAVORO_CHIUSO, eff)
            fine = arrotonda_su_minuto(ora + timedelta(minutes=cmd.minuti))
            if g.lv is not None:
                eff.append(Episodio("lv", g.lv.inizio, ora, minuti_interi_su(g.lv.inizio, ora), 0, {"perche": "sostituito"}))
            g.lv = Lavoro(inizio=ora, fine=fine)
            eff.append(Evento("lavoro", {"minuti": cmd.minuti, "fino": hhmm(fine)}))
            return Risposta(True, testi.LAVORO_OK.format(fino=hhmm(fine)), eff)
        # dm
        fine = arrotonda_su_minuto(ora + timedelta(minutes=cmd.minuti))
        if g.pausa is not None:
            self._chiudi_pausa(ora, eff, "dm")
        g.pausa_sforata = False
        g.dm = Dormo(inizio=ora, fine=fine)
        eff.append(Evento("dm", {"minuti": cmd.minuti, "fino": hhmm(fine)}))
        return Risposta(True, testi.DORMO_OK.format(fino=hhmm(fine)), eff)

    def sblocco(self, fino: datetime | None, ora: datetime) -> list:
        """Sblocco d'emergenza dal PC: modalità libero fino a quell'ora, niente punizioni."""
        eff = self.allinea(ora)
        self.s.sblocco_fino = fino
        eff.append(Evento("sblocco_emergenza", {"fino": fino.isoformat() if fino else None}))
        return eff

    # ---- giudizi che arrivano da SemIf -------------------------------------------------------

    def giudizio_pensiero(self, id_sospeso: str, esito: str, ora: datetime) -> list:
        eff = self.allinea(ora)
        g = self.s.giorno
        s = next((x for x in g.sospesi if x.id == id_sospeso), None)
        if s is None or s.stato != "da_giudicare":
            return eff
        if esito == "studio" and self.attivo(ora):
            s.credito = min(SOSPESO_MAX_STUDIO, s.minuti)
            s.stato = "studio"
            g.studio += s.credito
            eff.append(Episodio("sospeso", s.inizio, s.fine or ora, s.minuti, 0,
                                {"esito": "studio", "credito": s.credito}))
            eff.append(Evento("pensiero_studio", {"id": s.id, "minuti": s.minuti, "credito": s.credito}))
            self._controlla_quota(ora, eff)
        else:
            s.stato = "neutro"
            eff.append(Episodio("sospeso", s.inizio, s.fine or ora, s.minuti, 0, {"esito": esito}))
            eff.append(Evento("pensiero_neutro", {"id": s.id, "minuti": s.minuti, "esito": esito}))
        return eff

    def esito_pausa(self, id_pausa: str, esito: str, ora: datetime) -> list:
        """SemIf dice se quello che si vede torna col motivo. Solo `non_torna` è imbroglio."""
        eff = self.allinea(ora)
        g = self.s.giorno
        pausa = None
        if g.pausa is not None and g.pausa.id == id_pausa:
            pausa = g.pausa
        elif g.ultima_pausa is not None and g.ultima_pausa.id == id_pausa:
            pausa = g.ultima_pausa
        if pausa is None or pausa.falsa or esito != "non_torna" or not self.attivo(ora):
            return eff
        pausa.falsa = True
        if self.sblocco_attivo(ora):
            return eff
        aggiunta = self._aggiungi_imbroglio()
        eff.append(Evento("imbroglio", {"motivo": "motivo della pausa falso", "pausa": pausa.motivo,
                                        "aggiunta": aggiunta}))
        eff.append(Episodio("imbroglio", pausa.inizio, ora, 0, aggiunta,
                            {"motivo": "motivo della pausa falso", "pausa": pausa.motivo}))
        if g.pausa is pausa:
            self._chiudi_pausa(ora, eff, "motivo falso")
        self._voce(testi.VOCE_PAUSA_FALSA, ora, eff, "imbroglio")
        self._controlla_quota(ora, eff)
        return eff

    # ---- il minuto ---------------------------------------------------------------------------

    def tick(self, m: Minuto) -> list:
        ora = inizio_minuto(m.ora)
        eff = self.allinea(ora)
        g = self.s.giorno
        if g.ultimo_minuto is not None and ora <= g.ultimo_minuto:
            return eff  # minuto già classificato

        # Arrivo (regole, sezione 2).
        if m.visto and m.stanza:
            self.s.ultima_stanza = m.stanza
        if (not self.inattivo and g.scuola and g.arrivo is None and m.visto
                and ora.time() >= ORA_MINIMA_ARRIVO and self._assente_da_3_ore(ora)):
            g.arrivo = ora
            eff.append(Evento("arrivo", {"ora": hhmm(ora), "riporto": g.riporto}))
        if m.visto:
            self.s.ultimo_visto = ora
        if m.forse_visto:
            self.s.ultimo_forse_visto = ora

        if not self.attivo(ora):
            g.classe_ultima = Classe.NESSUNA.value
            g.ultimo_minuto = ora
            self._voce_rimandata(ora, eff)  # per esempio "Fatto per oggi" se era rimasta in attesa
            return eff

        self._scadenze(m, ora, eff)
        self._distrazione_toccata = False
        classe, motivo, aggiunta = self._classifica(m, ora, eff)
        ep = g.distrazione
        if ep is not None and not self._distrazione_toccata:
            # Un episodio si chiude anche dopo 5 minuti senza distrazione (regole, sezione 5).
            ep.senza += 1
            if ep.senza >= DISTRAZIONE_FINE_DOPO:
                self._chiudi_distrazione(ora, eff)
        if classe == Classe.STUDIO:
            g.studio += 1
        elif classe == Classe.LAVORO:
            g.lavoro += 1
        self._aggiorna_sospesi(classe, ora, eff)
        g.classe_ultima = classe.value
        g.ultimo_minuto = ora
        g.conteggio[classe.value] = g.conteggio.get(classe.value, 0) + 1
        eff.append(MinutoClassificato(ora, classe, motivo, aggiunta))
        self._controlla_quota(ora, eff)
        self._voce_rimandata(ora, eff)
        return eff

    def _assente_da_3_ore(self, ora: datetime) -> bool:
        for ultimo in (self.s.ultimo_visto, self.s.ultimo_forse_visto):
            if ultimo is not None and ora - ultimo < ASSENZA_PER_ARRIVO:
                return False
        return True

    def _scadenze(self, m: Minuto, ora: datetime, eff: list) -> None:
        g = self.s.giorno
        if g.pausa is not None and ora >= g.pausa.fine:
            self._chiudi_pausa(ora, eff, "scaduta")
            g.pausa_sforata = True
        if g.lv is not None and ora >= g.lv.fine:
            eff.append(Episodio("lv", g.lv.inizio, g.lv.fine, minuti_interi_su(g.lv.inizio, g.lv.fine), 0, {"perche": "scaduto"}))
            eff.append(Evento("lavoro_finito", {}))
            g.lv = None
        if g.dm is not None and ora >= g.dm.fine:
            if g.dm.stato == "valido":
                # Sforare non punisce: resta lui (la persona sdraiata in quel posto) finché non lo
                # vedono alzarsi.
                if not g.dm.sforato:
                    g.dm.sforato = True
                    eff.append(Evento("dm_scaduto", {"fino": hhmm(g.dm.fine)}))
            else:
                self._chiudi_dm(ora, eff, "scaduto")
        if g.dm is not None and g.dm.stato == "attesa":
            if m.visto and m.posa == "sdraiato" and m.dove in ("letto", "divano"):
                g.dm.stato = "valido"
                g.dm.stanza = m.stanza
                g.dm.dove = m.dove
                g.dm.confermato = ora + timedelta(minutes=1)
                eff.append(Evento("dm_valido", {"stanza": m.stanza, "dove": m.dove}))
            elif ora >= g.dm.inizio + DM_CONFERMA:
                self._chiudi_dm(ora, eff, "annullato: non visto sdraiato")
                eff.append(Evento("dm_annullato", {}))
                self._voce(testi.VOCE_DM_ANNULLATO, ora, eff, "dm_annullato", priorita=True)

    def _classifica(self, m: Minuto, ora: datetime, eff: list) -> tuple[Classe, str, int]:
        g = self.s.giorno
        pc = m.pc
        visto = m.visto
        if m.mangia and visto:
            g.visto_mangiare = True

        distr = self._prova_distrazione(m)
        # Le cose di lavoro sono permesse solo durante lv: fuori da lv il PC le copre (anche un sito
        # giudicato "lavoro"), quindi non contano né come studio né come "PC su una cosa permessa".
        permesse = ("studio", "lavoro") if self._lv_in_corso(ora) else ("studio",)
        imbr = self._prova_imbroglio(m, permesse)
        studio = None if (distr or imbr) else self._prova_studio(m)
        lavoro = None if (distr or imbr or studio) else self._prova_lavoro(m, ora)
        pc_permesso_in_uso = pc is not None and pc.in_uso and pc.categoria in permesse
        # PC toccato nell'ultimo minuto (qualunque cosa ci sia sopra): lo studente è lì.
        pc_toccato = self._input_recente(pc, ora)
        # Telecamere giù o visione ferma (tutte, o quella della stanza dove era visto per ultimo):
        # senza occhi non c'è prova, quindi niente fuori vista.
        cieco = not visto and (not m.telecamere_ok or (self.s.ultima_stanza is not None
                                                      and self.s.ultima_stanza in m.stanze_cieche))
        # Durante un dm valido (anche sforato) la persona sdraiata non riconosciuta è lui.
        sdraiato_dm = not visto and m.forse_visto and g.dm is not None and g.dm.stato == "valido"

        # Conteggio del fuori vista.
        if visto:
            if g.pranzo == "in_corso":
                g.pranzo = "usata"
                eff.append(Episodio("pranzo", g.pranzo_inizio or ora, ora, g.pranzo_minuti, 0, {"esito": "tornato in tempo"}))
                eff.append(Evento("pranzo", {"minuti": g.pranzo_minuti, "esito": "neutro"}))
            g.fuori_vista = 0
        elif (pc_toccato or sdraiato_dm) and g.pranzo != "in_corso":
            g.fuori_vista = 0
        elif cieco or g.pausa is not None or pc_permesso_in_uso:
            pass  # conteggio fermo: telecamere giù, pausa in corso, PC usato su una cosa permessa
        else:
            g.fuori_vista += 1

        # Episodio di imbroglio: si chiude dopo qualche minuto senza la prova.
        if not imbr and g.imbroglio is not None:
            g.imbroglio.senza += 1
            if g.imbroglio.senza >= IMBROGLIO_FINE_DOPO:
                self._chiudi_imbroglio(ora, eff)

        # 1. Studio e lavoro: avanzano la quota e chiudono pausa, sforo, distrazione.
        if studio or lavoro:
            self._torna_a_studiare(ora, eff)
            if studio:
                return Classe.STUDIO, studio, 0
            return Classe.LAVORO, lavoro, 0

        # 2. Pausa in corso: neutro. Se lo si vede, SemIf controlla che torni col motivo.
        if g.pausa is not None:
            p = g.pausa
            if visto:
                p.minuti_visto += 1
                if p.minuti_visto >= PAUSA_CONTROLLO_DOPO and (
                        p.ultimo_controllo is None or ora - p.ultimo_controllo >= PAUSA_CONTROLLO_OGNI):
                    p.ultimo_controllo = ora
                    eff.append(ChiediPausa(p.id, p.motivo, p.inizio))
            else:
                p.minuti_visto = 0
            return Classe.NEUTRO, "pausa", 0

        # 3. Dormo.
        if g.dm is not None:
            dm = g.dm
            if dm.stato == "attesa":
                if not (distr or imbr):
                    return Classe.NEUTRO, "dm (in attesa di vederti sdraiato)", 0
            else:
                # Il PC conta come "alzato" solo se toccato DOPO la conferma, nell'ultimo minuto: il
                # comando dm stesso si scrive al PC e non deve chiudere il dm.
                toccato_dopo = (pc_toccato and pc.ultimo_input is not None and dm.confermato is not None
                                and pc.ultimo_input >= dm.confermato)
                attivo = toccato_dopo or (visto and (m.posa == "in_piedi" or bool(m.in_mano)
                                                     or m.dove == "scrivania"))
                if attivo:
                    # Un minuto in piedi o attivo: il dm finisce (questo minuto resta neutro).
                    self._chiudi_dm(ora, eff, "alzato")
                    return Classe.NEUTRO, "dm finito: alzato", 0
                if visto or sdraiato_dm or g.fuori_vista <= FUORI_VISTA_NEUTRI:
                    return Classe.NEUTRO, "dm (sforato)" if dm.sforato else "dm", 0
                # Fuori vista per più di 5 minuti durante il dm: vale la regola normale.

        # Senza occhi niente prova: neutro (le prove del PC, come lo svago, valgono lo stesso).
        if cieco and not distr:
            return Classe.NEUTRO, "telecamere giù o visione ferma", 0

        # 4. Imbroglio: dispositivo non controllato in uso.
        if imbr:
            return self._imbroglio(ora, imbr[0], imbr[1], eff)

        # 5. Pausa sforata: fuori vista o distratto subito, senza minuto di filtro.
        if g.pausa_sforata:
            if not visto and not pc_permesso_in_uso and not pc_toccato:
                return self._distrazione(ora, "pausa sforata (fuori vista)", eff, immediata=True,
                                         frase=testi.VOCE_PAUSA_FINITA)
            if distr:
                return self._distrazione(ora, "pausa sforata: " + distr, eff, immediata=True,
                                         frase=testi.VOCE_PAUSA_FINITA)
            if visto or pc_toccato:
                # Tornato in vista (o al PC) e non distratto: lo sforo finisce qui.
                g.pausa_sforata = False

        # 6. Distrazione con prova chiara.
        if distr:
            return self._distrazione(ora, distr, eff, immediata=False)

        # 7. Fuori vista. Con il PC toccato nell'ultimo minuto lo studente è lì: niente fuori vista.
        if not visto and pc_toccato:
            return Classe.NEUTRO, "non visto ma il PC è in uso", 0
        if not visto:
            esito = self._fuori_vista(ora, pc_permesso_in_uso, eff)
            if esito is not None:
                return esito

        # 8. Neutri con motivo.
        neutro = self._prova_neutro(m)
        if neutro:
            return Classe.NEUTRO, neutro, 0

        # 9. Pensiero: fermo, niente in mano, occhi aperti, alla scrivania o sul divano.
        if visto and m.pensiero and m.dove in ("scrivania", "divano"):
            return Classe.SOSPESO, "pensiero", 0

        # 10. Nel dubbio, né avanti né punizione.
        return Classe.NEUTRO, "nel dubbio", 0

    def _fuori_vista(self, ora: datetime, pc_permesso_in_uso: bool, eff: list):
        g = self.s.giorno
        # Sparizione "pranzo" (una sola al giorno).
        if g.pranzo == "in_corso":
            g.pranzo_minuti += 1
            if g.pranzo_minuti <= PRANZO_DURATA_MAX:
                return Classe.NEUTRO, "pranzo", 0
            # Non è ricomparso entro 60 minuti. I 60 minuti concessi restano neutri, sempre: niente
            # all'indietro (come lo sforo della pausa, si paga solo il tempo oltre). Dal 61° minuto
            # vale la regola normale del fuori vista senza altri 5 minuti di grazia: distrazione,
            # con l'avviso a voce, finché non ricompare o scrive una pausa.
            g.pranzo = "persa"
            g.fuori_vista = max(g.fuori_vista, FUORI_VISTA_NEUTRI + 1)
            eff.append(Episodio("pranzo", g.pranzo_inizio or ora, ora, PRANZO_DURATA_MAX, 0,
                                {"esito": "non tornato entro 60 minuti"}))
            eff.append(Evento("pranzo", {"esito": "non tornato entro 60 minuti", "minuti_neutri": PRANZO_DURATA_MAX}))
            self._voce(testi.VOCE_PRANZO_FINITO, ora, eff, "fuori_vista")
            return self._distrazione(ora, "fuori vista oltre l'ora del pranzo", eff, immediata=True, frase=None)
        if (g.pranzo == "disponibile" and g.fuori_vista == 1 and not g.visto_mangiare
                and g.arrivo is not None and ora - g.arrivo <= PRANZO_ENTRO):
            g.pranzo = "in_corso"
            g.pranzo_inizio = ora
            g.pranzo_minuti = 1
            eff.append(Evento("pranzo_iniziato", {"ora": hhmm(ora)}))
            return Classe.NEUTRO, "pranzo", 0
        if pc_permesso_in_uso:
            return Classe.NEUTRO, "non visto ma il PC è usato su una cosa permessa", 0
        if g.fuori_vista <= FUORI_VISTA_NEUTRI:
            if g.fuori_vista == FUORI_VISTA_NEUTRI:
                self._voce(testi.VOCE_FUORI_VISTA, ora, eff, "fuori_vista")
            return Classe.NEUTRO, f"fuori vista ({g.fuori_vista} min)", 0
        return self._distrazione(ora, "fuori vista oltre 5 minuti", eff, immediata=True, frase=None)

    # ---- prove -------------------------------------------------------------------------------

    @staticmethod
    def _prova_studio(m: Minuto) -> str | None:
        if m.in_mano & OGGETTI_STUDIO:
            return "libro o quaderno di scuola in uso"
        if m.scrive and m.visto:
            return "scrive"
        pc = m.pc
        if pc is not None and m.visto:
            if pc.in_uso and pc.categoria == "studio" and m.dove == "scrivania":
                return "PC su una cosa di studio"
            if pc.audio_studio and not m.dorme:
                return "Lectio con le cuffie"
        return None

    @staticmethod
    def _input_recente(pc: PcMinuto | None, ora: datetime) -> bool:
        """Tasti o mouse dentro il minuto che si sta classificando (che comincia a `ora`)."""
        return pc is not None and pc.ultimo_input is not None and pc.ultimo_input >= ora

    @staticmethod
    def _minuti_usati(p: Pausa, ora: datetime) -> int:
        return min(p.minuti, minuti_interi_su(p.inizio, min(ora, p.fine)))

    def _lv_in_corso(self, ora: datetime) -> bool:
        lv = self.s.giorno.lv
        return lv is not None and ora < lv.fine

    def _prova_lavoro(self, m: Minuto, ora: datetime) -> str | None:
        if not self._lv_in_corso(ora):
            return None
        pc = m.pc
        if pc is not None and m.visto and pc.in_uso and pc.categoria == "lavoro" and m.dove == "scrivania":
            return "PC su una cosa di lavoro (lv)"
        return None

    @staticmethod
    def _prova_distrazione(m: Minuto) -> str | None:
        if m.in_mano & TELEFONI_SUOI:
            return "telefono in mano"
        if m.pc is not None and m.pc.in_uso and m.pc.categoria == "svago":
            return "svago sul PC"
        return None

    @staticmethod
    def _prova_imbroglio(m: Minuto, permesse: tuple[str, ...] = ("studio", "lavoro")) -> tuple[str, str] | None:
        if not m.visto:
            return None
        pc = m.pc
        if pc is not None and pc.in_uso and pc.categoria in permesse:
            return None  # il PC dice che lo schermo controllato è in uso su una cosa permessa
        if "controller" in m.in_mano and ("tv" in m.schermi or "console" in m.schermi):
            return "console accesa", "console"
        for dispositivo in sorted(m.in_mano & DISPOSITIVI_IMBROGLIO_IN_MANO):
            return f"{dispositivo.replace('_', ' ')} in mano", dispositivo
        for dispositivo in sorted(m.schermi):
            return f"{dispositivo.replace('_', ' ')} accesa davanti", dispositivo
        return None

    @staticmethod
    def _prova_neutro(m: Minuto) -> str | None:
        if m.dorme and m.visto:
            return "dorme"
        if m.mangia and m.visto:
            return "mangia"
        if m.in_mano & LETTURE_ALTRE:
            return "legge altro"
        return None

    # ---- episodi -----------------------------------------------------------------------------

    def _distrazione(self, ora: datetime, motivo: str, eff: list, immediata: bool,
                     frase: str | None = testi.VOCE_DISTRAZIONE) -> tuple[Classe, str, int]:
        g = self.s.giorno
        if self.sblocco_attivo(ora):
            return Classe.NEUTRO, "sblocco d'emergenza (" + motivo + ")", 0
        ep = g.distrazione
        self._distrazione_toccata = True
        if ep is None:
            g.distrazione = ep = EpisodioDistrazione(inizio=ora, motivo=motivo)
            if frase:
                self._voce(frase.format(mancano=self.mancano()), ora, eff, "distrazione")
            eff.append(Evento("distrazione_inizio", {"motivo": motivo}))
            if not immediata:
                # Il primo minuto filtra i falsi allarmi: avviso, ma non conta.
                return Classe.NEUTRO, "primo minuto di distrazione (avviso, non conta)", 0
        elif ep.ultimo_distratto is not None and ora - ep.ultimo_distratto > timedelta(minutes=1) and frase:
            # Ricomincia dentro lo stesso episodio (non ha ancora ripreso a studiare): ricorda.
            self._voce(frase.format(mancano=self.mancano()), ora, eff, "distrazione")
        ep.senza = 0
        aggiunta = self._aggiungi_distrazione(1)
        ep.minuti += 1
        ep.aggiunta += aggiunta
        ep.ultimo_distratto = ora
        return Classe.DISTRAZIONE, motivo, aggiunta

    def _imbroglio(self, ora: datetime, motivo: str, dispositivo: str, eff: list) -> tuple[Classe, str, int]:
        g = self.s.giorno
        if self.sblocco_attivo(ora):
            return Classe.NEUTRO, "sblocco d'emergenza (" + motivo + ")", 0
        ep = g.imbroglio
        aggiunta = 0
        if ep is None:
            aggiunta = self._aggiungi_imbroglio()
            g.imbroglio = EpisodioImbroglio(inizio=ora, motivo=motivo, dispositivo=dispositivo, aggiunta=aggiunta)
            eff.append(Evento("imbroglio", {"motivo": motivo, "dispositivo": dispositivo, "aggiunta": aggiunta}))
            self._voce(testi.VOCE_IMBROGLIO, ora, eff, "imbroglio")
            if dispositivo in ("tv", "console"):
                eff.append(SpegniPresa(dispositivo, self.s.ultima_stanza))
        else:
            ep.minuti += 1
            ep.senza = 0
        return Classe.IMBROGLIO, motivo, aggiunta

    def _aggiungi_distrazione(self, n: int) -> int:
        g = self.s.giorno
        spazio = min(TETTO_DISTRAZIONI - g.agg_distrazione, TETTO_AGGIUNTE - self.aggiunte())
        a = max(0, min(n, spazio))
        g.agg_distrazione += a
        return a

    def _aggiungi_imbroglio(self) -> int:
        g = self.s.giorno
        a = max(0, min(AGGIUNTA_IMBROGLIO, TETTO_AGGIUNTE - self.aggiunte()))
        g.agg_imbroglio += a
        return a

    def _torna_a_studiare(self, ora: datetime, eff: list) -> None:
        g = self.s.giorno
        if g.pausa is not None:
            self._chiudi_pausa(ora, eff, "tornato a studiare")
        g.pausa_sforata = False
        if g.dm is not None:
            self._chiudi_dm(ora, eff, "tornato a studiare")
        self._chiudi_distrazione(ora, eff)
        self._chiudi_imbroglio(ora, eff)

    def _chiudi_pausa(self, ora: datetime, eff: list, perche: str) -> None:
        g = self.s.giorno
        p = g.pausa
        if p is None:
            return
        fine = min(ora, p.fine)
        usati = self._minuti_usati(p, ora)
        g.pausa_usata -= (p.minuti - usati)  # i minuti non usati tornano disponibili
        eff.append(Episodio("pausa", p.inizio, fine, usati, 0, {"motivo": p.motivo, "perche": perche,
                                                                 "chiesti": p.minuti}))
        g.ultima_pausa = p
        g.pausa = None

    def _chiudi_dm(self, ora: datetime, eff: list, perche: str) -> None:
        g = self.s.giorno
        dm = g.dm
        if dm is None:
            return
        fine = ora if dm.sforato else min(ora, dm.fine)
        eff.append(Episodio("dm", dm.inizio, fine, minuti_interi_su(dm.inizio, fine), 0,
                            {"perche": perche, "stato": dm.stato, "sforato": dm.sforato}))
        g.dm = None

    def _chiudi_distrazione(self, ora: datetime, eff: list) -> None:
        g = self.s.giorno
        ep = g.distrazione
        if ep is None:
            return
        eff.append(Episodio("distrazione", ep.inizio, ora, ep.minuti, ep.aggiunta, {"motivo": ep.motivo}))
        g.distrazione = None

    def _chiudi_imbroglio(self, ora: datetime, eff: list) -> None:
        g = self.s.giorno
        ep = g.imbroglio
        if ep is None:
            return
        eff.append(Episodio("imbroglio", ep.inizio, ora, ep.minuti, ep.aggiunta,
                            {"motivo": ep.motivo, "dispositivo": ep.dispositivo}))
        g.imbroglio = None

    # ---- sospesi (pensiero) ------------------------------------------------------------------

    def _aggiorna_sospesi(self, classe: Classe, ora: datetime, eff: list) -> None:
        g = self.s.giorno
        corrente = next((s for s in g.sospesi if s.stato == "in_corso"), None)
        if classe == Classe.SOSPESO:
            if corrente is None:
                corrente = Sospeso(id=self._nuovo_id("s"), inizio=ora)
                g.sospesi.append(corrente)
            corrente.minuti += 1
        elif corrente is not None:
            corrente.fine = ora
            corrente.scadenza = ora + SOSPESO_FINESTRA_DOPO
            corrente.stato = "dopo"
        for s in g.sospesi:
            if s.stato != "dopo":
                continue
            if ora >= s.scadenza:
                s.stato = "neutro"
                eff.append(Episodio("sospeso", s.inizio, s.fine or ora, s.minuti, 0,
                                    {"esito": "neutro", "perche": "dopo non abbastanza studio"}))
                continue
            if classe == Classe.STUDIO:
                s.dopo += 1
                if s.dopo >= s.minuti:
                    s.stato = "da_giudicare"
                    eff.append(ChiediPensiero(s.id, s.inizio, s.fine or ora, ora + timedelta(minutes=1), s.minuti))

    # ---- quota e voce ------------------------------------------------------------------------

    def _controlla_quota(self, ora: datetime, eff: list) -> None:
        g = self.s.giorno
        if g.fatta_alle is not None or g.arrivo is None or not g.scuola:
            return
        if self.fatti() < self.totale():
            return
        g.fatta_alle = ora
        self._chiudi_tutto(ora, eff, perche="quota fatta")
        for s in g.sospesi:
            if s.stato in ("dopo", "da_giudicare"):
                s.stato = "neutro"
        eff.append(Evento("quota_fatta", {"fatti": self.fatti(), "totale": self.totale(), "ora": hhmm(ora)}))
        eff.append(QuotaFatta(ora))
        self._voce(testi.VOCE_QUOTA_FATTA, ora, eff, "quota_fatta", priorita=True)

    def _dm_in_corso(self) -> bool:
        return self.s.giorno.dm is not None

    def _voce(self, testo: str, ora: datetime, eff: list, motivo: str, priorita: bool = False) -> None:
        if self._dm_in_corso():
            return  # mai durante un dm
        if self.sblocco_attivo(ora) and motivo != "quota_fatta":
            return
        if self.s.ultima_voce is not None and ora - self.s.ultima_voce < VOCE_OGNI:
            if priorita:
                self.s.voce_in_attesa = testo
            return
        self.s.ultima_voce = ora
        eff.append(Voce(testo, self.s.ultima_stanza, motivo))

    def _voce_rimandata(self, ora: datetime, eff: list) -> None:
        testo = self.s.voce_in_attesa
        if not testo or self._dm_in_corso():
            return
        if self.s.ultima_voce is not None and ora - self.s.ultima_voce < VOCE_OGNI:
            return
        self.s.voce_in_attesa = None
        self.s.ultima_voce = ora
        eff.append(Voce(testo, self.s.ultima_stanza, "rimandata"))

    def _nuovo_id(self, prefisso: str) -> str:
        self.s.contatore += 1
        return f"{prefisso}{self.s.giorno.data.strftime('%Y%m%d')}-{self.s.contatore}"
