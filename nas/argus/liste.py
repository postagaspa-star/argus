"""Le liste di programmi e siti (regole sezione 14) e le modifiche con `ag` / `tg` (sezione 8).

Regole di confronto (contratto, sezione 3, uguali sul NAS e sul PC):
- programma: nome dell'eseguibile minuscolo, uguaglianza esatta. Un nome in lista senza ".exe"
  vale anche come prefisso del nome del file senza estensione;
- sito: dominio minuscolo; vale se è uguale o finisce con "." + voce. Le voci che finiscono con
  "." (per esempio "192.168.") valgono come prefisso; "localhost" e "127.0.0.1" anche con la porta;
- "mai" vince su tutto.

Le aggiunte valgono dopo 4 giorni, le tolte subito. La versione delle liste è il numero di
modifiche già in vigore: cambia da sola quando un'aggiunta diventa valida.

`liste_extra` (config.json del NAS, contratto sezione 6): voci locali che non stanno nel repo
pubblico (per esempio i siti dei clienti). Valgono subito; quando cambiano, la versione sale di uno.
"""

from __future__ import annotations

import copy
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import testi
from .tempo import a_fuso

GIORNI_ATTESA_AGGIUNTA = 4

BROWSER = ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"]

LISTE_PARTENZA: dict = {
    "sempre": {
        "programmi": [
            # I programmi di Argus per nome esatto (il terminale è dentro l'agente). Un prefisso
            # "argus" lascerebbe passare un gioco rinominato "argusgioco.exe".
            "argus.agente.exe",
            "argus.sblocco.exe",
            "argus.guardiano.exe",
            "explorer.exe",
            "calculatorapp.exe",
            "calculator.exe",
            "notepad.exe",
            "snippingtool.exe",
            "screenclippinghost.exe",
            "pactum.exe",
            "consent.exe",
            "lockapp.exe",
            "searchhost.exe",
            "startmenuexperiencehost.exe",
            "shellexperiencehost.exe",
        ],
        "siti": [],
    },
    "studio": {
        "programmi": [
            "soffice.exe",
            "swriter.exe",
            "scalc.exe",
            "simpress.exe",
            "smath.exe",
            "sdraw.exe",
            "pdfelement.exe",
            "lectio",
            "googledrivefs.exe",
            "photos.exe",
            "microsoft.photos.exe",
            "soundrec.exe",
            "voicerecorder.exe",
        ],
        "siti": [
            "spaggiari.eu",
            "classeviva.it",
            "drive.google.com",
            "docs.google.com",
            "classroom.google.com",
            "zanichelli.it",
            "pearson.it",
            "hubscuola.it",
            "mondadorieducation.it",
            "deascuola.it",
            "bsmart.it",
            "loescher.it",
            "wikipedia.org",
            "treccani.it",
            "wordreference.com",
            "translate.google.com",
            "deepl.com",
            "brocardi.it",
            "normattiva.it",
            "geogebra.org",
            "desmos.com",
            "wolframalpha.com",
            "khanacademy.org",
        ],
    },
    "lavoro": {
        "programmi": [
            "claude.exe",
            "windowsterminal.exe",
            "powershell.exe",
            "cmd.exe",
            "git-bash.exe",
            "bash.exe",
            "mintty.exe",
            "git-gui.exe",
            "wish.exe",
            "studio64.exe",
            "python.exe",
            "pythonw.exe",
            "node.exe",
            "devhome.exe",
            "wisper ufficio",
            "wisperufficio.exe",
            "ugreen nas",
            "lm studio.exe",
            "bionic.exe",  # LM Studio: l'eseguibile vero si chiama così
            "ollama app.exe",
            "outlook.exe",
            "olk.exe",
            "epsonscan2.exe",
        ],
        "siti": [
            "github.com",
            "githubusercontent.com",
            "netlify.com",
            "netlify.app",
            "firebase.google.com",
            "console.cloud.google.com",
            "cloudflare.com",
            "tailscale.com",
            "huggingface.co",
            "devpost.com",
            "stackoverflow.com",
            "developer.mozilla.org",
            "docs.python.org",
            "developer.android.com",
            "learn.microsoft.com",
            "mail.google.com",
            "localhost",
            "127.0.0.1",
            "192.168.",
        ],
    },
    "da_giudicare": [
        "youtube.com",
        "claude.ai",
        "chatgpt.com",
        "gemini.google.com",
        "grok.com",
        "copilot.microsoft.com",
    ],
    "mai": {
        "programmi": [
            "steam.exe",
            "steamwebhelper.exe",
            "steamservice.exe",
            "minecraft",
            "minecraftlauncher.exe",
            "albion",
            "crusader kings",
            "ck2.exe",
            "ck3.exe",
            "hearts of iron",
            "hoi4.exe",
            "war thunder",
            "aces.exe",
            "paradox launcher",
            "paradoxlauncher.exe",
            "schedule i",
            "xbox",
            "gamebar.exe",
            "solitaire",
            "whatsapp.exe",
            "whatsapp",
            "teams.exe",
            "ms-teams.exe",
        ],
        "siti": [
            "instagram.com",
            "tiktok.com",
            "x.com",
            "twitter.com",
            "reddit.com",
            "facebook.com",
            "twitch.tv",
            "netflix.com",
            "primevideo.com",
            "disneyplus.com",
            "web.whatsapp.com",
            "msn.com",
        ],
    },
    "browser": BROWSER,
    # Campo in più rispetto all'esempio del contratto (aggiunta compatibile): programmi permessi
    # solo con certi titoli di finestra (regole sezione 14).
    "condizionati": {"applicationframehost.exe": ["Calcolatrice", "Strumento di cattura"]},
}


# ---------------------------------------------------------------------------------------------
# Confronto
# ---------------------------------------------------------------------------------------------

def _senza_estensione(nome: str) -> str:
    return nome[:-4] if nome.endswith(".exe") else nome


def programma_in(processo: str | None, voci: list[str]) -> bool:
    if not processo:
        return False
    nome = processo.strip().lower()
    base = _senza_estensione(nome)
    for voce in voci:
        v = voce.strip().lower()
        if not v:
            continue
        if nome == v:
            return True
        if not v.endswith(".exe") and base.startswith(v):
            return True
    return False


def normalizza_dominio(dominio: str | None) -> str:
    if not dominio:
        return ""
    d = dominio.strip().lower().rstrip(".")
    if "://" in d:
        d = d.split("://", 1)[1]
    d = d.split("/", 1)[0]
    # Toglie la porta (ma non rompe gli indirizzi IPv6 tra parentesi).
    if d.startswith("["):
        d = d.split("]", 1)[0] + "]"
    elif d.count(":") == 1:
        d = d.split(":", 1)[0]
    return d


def sito_in(dominio: str | None, voci: list[str]) -> bool:
    d = normalizza_dominio(dominio)
    if not d:
        return False
    for voce in voci:
        v = voce.strip().lower()
        if not v:
            continue
        if v.endswith("."):
            if d.startswith(v):
                return True
            continue
        if d == v or d.endswith("." + v):
            return True
    return False


def e_browser(processo: str | None, liste: dict) -> bool:
    return programma_in(processo, liste.get("browser", BROWSER))


def in_mai(processo: str | None, dominio: str | None, liste: dict) -> bool:
    mai = liste["mai"]
    return programma_in(processo, mai["programmi"]) or sito_in(dominio, mai["siti"])


# ---------------------------------------------------------------------------------------------
# Modifiche con ag / tg
# ---------------------------------------------------------------------------------------------

@dataclass
class Modifica:
    azione: str  # "ag" | "tg"
    lista: str  # "studio" | "lavoro"
    tipo: str  # "programmi" | "siti"
    voce: str
    quando: datetime
    valida_da: datetime
    annullata: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def a_dict(self) -> dict:
        return {
            "id": self.id,
            "azione": self.azione,
            "lista": self.lista,
            "tipo": self.tipo,
            "voce": self.voce,
            "quando": self.quando.isoformat(),
            "valida_da": self.valida_da.isoformat(),
            "annullata": self.annullata,
        }

    @staticmethod
    def da_dict(d: dict) -> "Modifica":
        return Modifica(
            azione=d["azione"],
            lista=d["lista"],
            tipo=d["tipo"],
            voce=d["voce"],
            quando=a_fuso(datetime.fromisoformat(d["quando"])),
            valida_da=a_fuso(datetime.fromisoformat(d["valida_da"])),
            annullata=bool(d.get("annullata", False)),
            id=d.get("id") or uuid.uuid4().hex[:12],
        )


_RE_DOMINIO = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+\.?$")
_RE_PROGRAMMA = re.compile(r"^[a-z0-9 _.+()&'-]{1,80}$")


def leggi_voce(testo: str) -> tuple[str, str] | None:
    """Capisce se la voce è un programma o un sito. Ritorna (tipo, voce normalizzata) o None."""
    t = testo.strip().lower().strip('"').strip("'").strip()
    if not t:
        return None
    if t.endswith(".exe"):
        return ("programmi", t) if _RE_PROGRAMMA.match(t) else None
    if "://" in t or "/" in t or "." in t:
        d = normalizza_dominio(t)
        if d.startswith("www."):
            d = d[4:]
        if d in ("localhost",) or _RE_DOMINIO.match(d):
            return ("siti", d)
        return None
    if t == "localhost":
        return ("siti", t)
    # Nome senza ".exe" (per esempio "wisper ufficio"): vale come prefisso del programma.
    return ("programmi", t) if _RE_PROGRAMMA.match(t) else None


class Liste:
    """Liste di partenza + modifiche (in vigore o in attesa). Pura: l'ora la passa chi chiama."""

    def __init__(self, modifiche: list[Modifica] | None = None, partenza: dict | None = None,
                 extra: dict | None = None, versione_extra: int = 0):
        self.modifiche: list[Modifica] = list(modifiche or [])
        self._partenza = copy.deepcopy(partenza or LISTE_PARTENZA)
        self.versione_extra = versione_extra
        # Le voci extra si aggiungono alle liste di partenza ("mai" vince comunque).
        for lista, gruppi in (extra or {}).items():
            if lista not in ("studio", "lavoro", "sempre") or not isinstance(gruppi, dict):
                continue
            for tipo in ("programmi", "siti"):
                for voce in gruppi.get(tipo) or []:
                    v = str(voce).strip().lower()
                    elenco = self._partenza[lista][tipo]
                    if v and v not in elenco and not self._in_mai(tipo, v):
                        elenco.append(v)

    def attive(self, ora: datetime) -> dict:
        liste = copy.deepcopy(self._partenza)
        for m in sorted(self.modifiche, key=lambda x: x.quando):
            if m.annullata or m.valida_da > ora:
                continue
            elenco = liste[m.lista][m.tipo]
            if m.azione == "ag":
                if m.voce not in elenco and not self._in_mai(m.tipo, m.voce):
                    elenco.append(m.voce)
            elif m.azione == "tg":
                if m.voce in elenco:
                    elenco.remove(m.voce)
        return liste

    def versione(self, ora: datetime) -> int:
        return 1 + self.versione_extra + sum(1 for m in self.modifiche if not m.annullata and m.valida_da <= ora)

    def per_pc(self, ora: datetime) -> dict:
        liste = self.attive(ora)
        return {
            "versione": self.versione(ora),
            "sempre": liste["sempre"],
            "studio": liste["studio"],
            "lavoro": liste["lavoro"],
            "da_giudicare": liste["da_giudicare"],
            "mai": liste["mai"],
            "browser": liste["browser"],
            "condizionati": liste.get("condizionati", {}),
        }

    def in_attesa(self, ora: datetime) -> list[Modifica]:
        return [m for m in self.modifiche if not m.annullata and m.valida_da > ora]

    def _in_mai(self, tipo: str, voce: str) -> bool:
        mai = self._partenza["mai"]
        if tipo == "programmi":
            return programma_in(voce, mai["programmi"]) or voce in mai["programmi"]
        return sito_in(voce, mai["siti"])

    def aggiungi(self, lista: str, testo_voce: str, ora: datetime) -> tuple[bool, str, Modifica | None]:
        letta = leggi_voce(testo_voce)
        if letta is None:
            return False, testi.LISTA_VOCE_NON_VALIDA, None
        tipo, voce = letta
        if self._in_mai(tipo, voce):
            return True, testi.LISTA_E_MAI.format(voce=voce), None
        attive = self.attive(ora)
        if voce in attive[lista][tipo]:
            return True, testi.LISTA_GIA_PRESENTE.format(voce=voce, lista=lista), None
        for m in self.in_attesa(ora):
            if m.azione == "ag" and m.lista == lista and m.voce == voce:
                return True, testi.LISTA_GIA_IN_ATTESA.format(
                    voce=voce, lista=lista, quando=_quando(m.valida_da)), None
        m = Modifica("ag", lista, tipo, voce, ora, ora + timedelta(days=GIORNI_ATTESA_AGGIUNTA))
        self.modifiche.append(m)
        return True, testi.LISTA_AGGIUNTA.format(voce=voce, lista=lista, quando=_quando(m.valida_da)), m

    def togli(self, lista: str, testo_voce: str, ora: datetime) -> tuple[bool, str, Modifica | None]:
        letta = leggi_voce(testo_voce)
        if letta is None:
            return False, testi.LISTA_VOCE_NON_VALIDA, None
        tipo, voce = letta
        annullate = 0
        for m in self.in_attesa(ora):
            if m.azione == "ag" and m.lista == lista and m.voce == voce:
                m.annullata = True
                annullate += 1
        attive = self.attive(ora)
        if voce not in attive[lista][tipo]:
            if annullate:
                return True, testi.LISTA_TOLTA.format(voce=voce, lista=lista), None
            return True, testi.LISTA_NON_PRESENTE.format(voce=voce, lista=lista), None
        m = Modifica("tg", lista, tipo, voce, ora, ora)
        self.modifiche.append(m)
        return True, testi.LISTA_TOLTA.format(voce=voce, lista=lista), m


def _quando(ora: datetime) -> str:
    return a_fuso(ora).strftime("%d/%m alle %H:%M")
