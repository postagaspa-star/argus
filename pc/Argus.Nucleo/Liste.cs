using System.Net;
using System.Text.Json;

namespace Argus.Nucleo;

/// <summary>Programmi e siti di un gruppo delle liste.</summary>
public sealed class GruppoListe
{
    public List<string> Programmi { get; set; } = new();
    public List<string> Siti { get; set; } = new();
}

/// <summary>
/// Le liste (contratto, GET /api/pc/liste; regole 14). Il NAS è la fonte; quelle di partenza (<see cref="Iniziali"/>)
/// valgono solo finché il NAS non ha mai risposto.
/// </summary>
public sealed class Liste
{
    public int Versione { get; set; }
    public GruppoListe Sempre { get; set; } = new();
    public GruppoListe Studio { get; set; } = new();
    public GruppoListe Lavoro { get; set; } = new();
    public List<string> DaGiudicare { get; set; } = new();
    public GruppoListe Mai { get; set; } = new();
    public List<string> Browser { get; set; } = new();

    public static Liste DaJson(string json)
    {
        var l = JsonSerializer.Deserialize<Liste>(json, JsonArgus.Opzioni) ?? throw new JsonException("liste vuote");
        return l.Normalizzate();
    }

    /// <summary>Tutto minuscolo e pulito: programmi senza spazi ai lati, siti senza schema, percorso e porta.</summary>
    public Liste Normalizzate()
    {
        static List<string> P(IEnumerable<string>? v) =>
            (v ?? Array.Empty<string>()).Select(Confronto.NormalizzaProgramma).Where(s => s.Length > 0).Distinct().ToList();
        static List<string> S(IEnumerable<string>? v) =>
            (v ?? Array.Empty<string>()).Select(Confronto.NormalizzaVoceSito).Where(s => s.Length > 0).Distinct().ToList();
        static GruppoListe G(GruppoListe? g) => new() { Programmi = P(g?.Programmi), Siti = S(g?.Siti) };
        return new Liste
        {
            Versione = Versione,
            Sempre = G(Sempre),
            Studio = G(Studio),
            Lavoro = G(Lavoro),
            Mai = G(Mai),
            DaGiudicare = S(DaGiudicare),
            Browser = P(Browser),
        };
    }

    public bool ÈBrowser(string exe) => Browser.Contains(Confronto.NormalizzaProgramma(exe));

    /// <summary>Le liste di partenza (regole 14), versione 0: valgono solo finché il NAS non ha mai risposto.</summary>
    public static Liste Iniziali() => new Liste
    {
        Versione = 0,
        Sempre = new GruppoListe
        {
            Programmi =
            {
                "argus.agente.exe", "argus.sblocco.exe", "explorer.exe", "calculatorapp.exe", "calculator.exe",
                "notepad.exe", "snippingtool.exe", "screenclippinghost.exe", "pactum.exe", "consent.exe",
                "lockapp.exe", "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
                "applicationframehost.exe",
            },
        },
        Studio = new GruppoListe
        {
            Programmi =
            {
                "soffice.exe", "swriter.exe", "scalc.exe", "simpress.exe", "smath.exe", "sdraw.exe", "pdfelement.exe",
                "lectio", "googledrivefs.exe", "photos.exe", "microsoft.photos.exe", "soundrec.exe", "voicerecorder.exe",
                "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
            },
            Siti =
            {
                "spaggiari.eu", "classeviva.it", "drive.google.com", "docs.google.com", "classroom.google.com",
                "zanichelli.it", "pearson.it", "hubscuola.it", "mondadorieducation.it", "deascuola.it", "bsmart.it",
                "loescher.it", "wikipedia.org", "treccani.it", "wordreference.com", "translate.google.com", "deepl.com",
                "brocardi.it", "normattiva.it", "geogebra.org", "desmos.com", "wolframalpha.com", "khanacademy.org",
            },
        },
        Lavoro = new GruppoListe
        {
            Programmi =
            {
                "claude.exe", "windowsterminal.exe", "powershell.exe", "cmd.exe", "git-bash.exe", "bash.exe",
                "mintty.exe", "git-gui.exe", "wish.exe", "studio64.exe", "python.exe", "pythonw.exe", "node.exe",
                "devhome.exe", "wisper ufficio", "wisperufficio.exe", "ugreen nas", "lm studio.exe", "bionic.exe",
                "ollama app.exe", "outlook.exe", "olk.exe", "epsonscan2.exe",
            },
            Siti =
            {
                "github.com", "githubusercontent.com", "netlify.com", "netlify.app", "firebase.google.com",
                "console.cloud.google.com", "cloudflare.com", "tailscale.com", "huggingface.co", "devpost.com",
                "stackoverflow.com", "developer.mozilla.org", "docs.python.org", "developer.android.com",
                "learn.microsoft.com", "mail.google.com", "localhost", "127.0.0.1", "192.168.",
            },
        },
        DaGiudicare = { "youtube.com", "claude.ai", "chatgpt.com", "gemini.google.com", "grok.com", "copilot.microsoft.com" },
        Mai = new GruppoListe
        {
            Programmi =
            {
                "steam.exe", "minecraft", "albion", "crusader kings", "hearts of iron", "war thunder", "paradox launcher",
                "schedule i", "xbox", "solitaire", "whatsapp.exe", "teams.exe", "ms-teams.exe",
            },
            Siti =
            {
                "instagram.com", "tiktok.com", "x.com", "twitter.com", "reddit.com", "facebook.com", "twitch.tv",
                "netflix.com", "primevideo.com", "disneyplus.com", "web.whatsapp.com", "msn.com",
            },
        },
        Browser = { "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe" },
    }.Normalizzate();
}

/// <summary>Le regole di confronto del contratto (sezione 3, uguali sul NAS e sul PC).</summary>
public static class Confronto
{
    public static string NormalizzaProgramma(string? voce) => (voce ?? "").Trim().ToLowerInvariant();

    /// <summary>
    /// Programma: nome dell'eseguibile minuscolo, uguaglianza esatta. Una voce senza ".exe" ("wisper ufficio")
    /// vale anche come prefisso del nome del file senza estensione.
    /// </summary>
    public static bool ProgrammaInLista(string exe, IEnumerable<string> voci)
    {
        var nome = NormalizzaProgramma(exe);
        if (nome.Length == 0) return false;
        var senzaEstensione = nome.EndsWith(".exe", StringComparison.Ordinal) ? nome[..^4] : nome;
        foreach (var grezza in voci)
        {
            var voce = NormalizzaProgramma(grezza);
            if (voce.Length == 0) continue;
            if (voce == nome) return true;
            if (!voce.EndsWith(".exe", StringComparison.Ordinal) && senzaEstensione.StartsWith(voce, StringComparison.Ordinal))
                return true;
        }
        return false;
    }

    /// <summary>
    /// Sito: il dominio della barra (minuscolo) vale se è uguale alla voce o finisce con "." + voce.
    /// Casi speciali: una voce che finisce con "." ("192.168.") è un prefisso di indirizzi IP; "localhost" e
    /// "127.0.0.1" valgono solo uguali.
    /// </summary>
    public static bool SitoInLista(string? dominio, IEnumerable<string> voci)
    {
        if (string.IsNullOrEmpty(dominio)) return false;
        var d = dominio.Trim().TrimEnd('.').ToLowerInvariant();
        if (d.Length == 0) return false;
        bool èIp = IPAddress.TryParse(d, out _);
        foreach (var grezza in voci)
        {
            var voce = NormalizzaVoceSito(grezza);
            if (voce.Length == 0) continue;
            if (voce.EndsWith('.'))
            {
                if (èIp && d.StartsWith(voce, StringComparison.Ordinal)) return true;
                continue;
            }
            if (d == voce) return true;
            if (!èIp && voce != "localhost" && !IPAddress.TryParse(voce, out _) && d.EndsWith("." + voce, StringComparison.Ordinal))
                return true;
        }
        return false;
    }

    /// <summary>Una voce di sito pulita: minuscola, senza schema, percorso, porta, "*." davanti.</summary>
    public static string NormalizzaVoceSito(string? voce)
    {
        var v = (voce ?? "").Trim().ToLowerInvariant();
        int schema = v.IndexOf("://", StringComparison.Ordinal);
        if (schema >= 0) v = v[(schema + 3)..];
        int fine = v.IndexOfAny(new[] { '/', '?', '#' });
        if (fine >= 0) v = v[..fine];
        if (v.StartsWith("*.", StringComparison.Ordinal)) v = v[2..];
        // La porta si toglie, ma non da un prefisso IP ("192.168.") né da un IPv6.
        int dueP = v.LastIndexOf(':');
        if (dueP > 0 && v.IndexOf(':') == dueP && v[(dueP + 1)..].All(char.IsAsciiDigit)) v = v[..dueP];
        v = v.TrimStart('.');
        return Indirizzi.SenzaWww(v);
    }
}

/// <summary>Dal testo della barra degli indirizzi al nome del sito. Il testo intero non esce da qui.</summary>
public static class Indirizzi
{
    /// <summary>
    /// "www." davanti non conta: Chrome lo nasconde nella barra (si legge "youtube.com" anche su www.youtube.com),
    /// Edge e Firefox no. Così lo stesso sito ha lo stesso nome (e la stessa chiave del verdetto) in ogni browser,
    /// e una voce di lista scritta "www.youtube.com" vale come "youtube.com".
    /// </summary>
    public static string SenzaWww(string host) =>
        host.StartsWith("www.", StringComparison.Ordinal) && host.IndexOf('.', 4) > 4 ? host[4..] : host;

    private static readonly string[] SchemiNonSiti =
    {
        "about:", "chrome:", "edge:", "brave:", "opera:", "vivaldi:", "view-source:", "data:", "javascript:",
        "mailto:", "file:", "blob:", "chrome-extension:", "moz-extension:", "extension:", "devtools:",
    };

    /// <summary>
    /// Il nome intero del sito (minuscolo, "it.wikipedia.org"), oppure null se la barra non mostra un sito
    /// (vuota, una ricerca, una pagina interna del browser, un file). Accetta anche "localhost" e gli IP.
    /// </summary>
    public static string? HostDaBarra(string? testo)
    {
        if (string.IsNullOrWhiteSpace(testo)) return null;
        var t = testo.Trim();
        if (t.Length > 4096) return null;
        foreach (var c in t)
        {
            if (char.IsWhiteSpace(c)) return null; // una ricerca, non un indirizzo
        }

        string conSchema;
        int schema = t.IndexOf("://", StringComparison.Ordinal);
        if (schema >= 0)
        {
            var nomeSchema = t[..schema].ToLowerInvariant();
            if (nomeSchema != "http" && nomeSchema != "https") return null;
            conSchema = t;
        }
        else
        {
            var minuscolo = t.ToLowerInvariant();
            foreach (var s in SchemiNonSiti)
            {
                if (minuscolo.StartsWith(s, StringComparison.Ordinal)) return null;
            }
            // "host:porta/..." sì; "qualcosa:altro" (uno schema sconosciuto) no.
            int fineHost = t.IndexOfAny(new[] { '/', '?', '#' });
            var testa = fineHost >= 0 ? t[..fineHost] : t;
            int dueP = testa.LastIndexOf(':');
            if (dueP >= 0 && !testa.StartsWith('['))
            {
                var porta = testa[(dueP + 1)..];
                if (porta.Length == 0 || !porta.All(char.IsAsciiDigit)) return null;
            }
            conSchema = "http://" + t;
        }

        if (!Uri.TryCreate(conSchema, UriKind.Absolute, out var uri)) return null;
        string host;
        switch (uri.HostNameType)
        {
            case UriHostNameType.Dns:
                try
                {
                    host = uri.IdnHost;
                }
                catch (UriFormatException)
                {
                    return null;
                }
                // Un nome senza punti è un sito solo se è "localhost" (altrimenti è una parola cercata).
                if (!host.Contains('.') && !host.Equals("localhost", StringComparison.OrdinalIgnoreCase)) return null;
                break;
            case UriHostNameType.IPv4:
                host = uri.Host;
                break;
            case UriHostNameType.IPv6:
                host = uri.Host.Trim('[', ']');
                break;
            default:
                return null;
        }
        host = SenzaWww(host.Trim().TrimEnd('.').ToLowerInvariant());
        return host.Length == 0 ? null : host;
    }
}
