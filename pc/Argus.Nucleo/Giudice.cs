using System.Drawing;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace Argus.Nucleo;

/// <summary>Quello che serve sapere della finestra in primo piano (mai il titolo: quello si chiede solo se serve).</summary>
/// <param name="IdFinestra">L'handle della finestra (per i 20 secondi del browser senza dominio).</param>
/// <param name="Exe">Il nome dell'eseguibile, minuscolo.</param>
/// <param name="Percorso">Il percorso del file del programma, se si legge.</param>
/// <param name="Riconosciuto">
/// Il programma riconosciuto dal percorso (<see cref="RiconoscitoreProgrammi"/>). Senza, il programma vale come
/// non riconosciuto: il nome da solo non basta mai (revisione B5).
/// </param>
public sealed record InfoFinestra(long IdFinestra, string Exe, string? Percorso = null, Riconoscimento? Riconosciuto = null);

/// <summary>Il giudizio sulla finestra in primo piano.</summary>
/// <param name="Permesso">Permessa nella modalità di adesso.</param>
/// <param name="DaCoprire">Va coperta (solo in studio e lavoro).</param>
/// <param name="Motivo">Per il diario tecnico e le prove ("mai", "studio", "fuori_lista", "attesa_giudizio"...).</param>
/// <param name="Dominio">Il dominio letto (per i browser), da mandare nel campione.</param>
/// <param name="Titolo">Il titolo da mandare nel campione: solo quando il contratto lo chiede, altrimenti null.</param>
/// <param name="Chiave">La chiave del verdetto per i siti da giudicare.</param>
public sealed record Giudizio(bool Permesso, bool DaCoprire, string Motivo, string? Dominio = null, string? Titolo = null, string? Chiave = null);

/// <summary>
/// Decide se la finestra in primo piano è permessa (regole 12 e 14, contratto sezione 3).
/// <list type="bullet">
/// <item>"mai" vince su tutto (anche i giochi lanciati da Steam, riconosciuti dalla cartella), col nome del file,
/// col nome originale scritto nel file o con quello riconosciuto;</item>
/// <item>i programmi di Argus sono sempre permessi, ma solo dalla loro cartella in Program Files;</item>
/// <item>le liste valgono solo per i programmi riconosciuti (cartella protetta, firma valida col nome originale,
/// percorsi fidati): un gioco rinominato "soffice.exe" nei Download non è LibreOffice;</item>
/// <item>browser: solo sui siti permessi nella modalità; senza dominio leggibile 20 secondi per finestra
/// (che non ripartono cambiando finestra), poi coperto;</item>
/// <item>siti da giudicare: permessi in attesa del verdetto per al massimo 20 secondi per pagina
/// (chiave = sha1(dominio + "|" + titolo)), poi coperti se il verdetto non è studio (o lavoro, durante lv);</item>
/// <item>applicationframehost.exe solo se il titolo è Calcolatrice o Strumento di cattura;</item>
/// <item>tutto il resto: coperto.</item>
/// </list>
/// Non è thread-safe: lo usa un solo thread (il sensore).
/// </summary>
public sealed class GiudiceFinestra
{
    public const long AttesaMs = 20_000;
    private const int MassimoMemorie = 500;

    /// <summary>I programmi di Argus: sempre permessi, qualunque cosa dicano le liste.</summary>
    public static readonly IReadOnlySet<string> ProgrammiArgus =
        new HashSet<string>(StringComparer.Ordinal) { "argus.agente.exe", "argus.sblocco.exe", "argus.guardiano.exe" };

    private static readonly HashSet<string> TitoliCorniceApp = new(StringComparer.OrdinalIgnoreCase)
    {
        "Calcolatrice", "Strumento di cattura", "Calculator", "Snipping Tool",
    };

    private readonly Dictionary<string, long> attesaVerdetto = new(StringComparer.Ordinal);
    private readonly Dictionary<long, long> senzaDominioDal = new();

    /// <param name="dominio">Il dominio letto dalla barra (null se non si legge o non c'è un sito). Conta solo per i browser.</param>
    /// <param name="titolo">Chiede il titolo della finestra: si chiama solo quando serve.</param>
    public Giudizio Giudica(InfoFinestra f, string? dominio, Func<string?> titolo, Liste liste, Modalita modalita,
        IReadOnlyDictionary<string, string>? verdetti, long adessoMs)
    {
        var r = f.Riconosciuto ?? new Riconoscimento(Confronto.NormalizzaProgramma(f.Exe), null, ComeRiconosciuto.SenzaPercorso);
        if (r.Come == ComeRiconosciuto.Argus) return new Giudizio(true, false, "argus");

        bool copre = Modalitas.Copre(modalita);
        bool lavoro = modalita == Modalita.Lavoro;
        var exe = r.Nome; // null = non riconosciuto: nessuna lista vale (tranne "mai")
        bool browser = exe != null && liste.ÈBrowser(exe);

        if (browser) return GiudicaBrowser(f, r, dominio, titolo, liste, modalita, verdetti, adessoMs);

        // Il titolo si manda solo per i programmi delle liste studio/lavoro (contratto: serve al diario).
        bool diLista = exe != null && (Confronto.ProgrammaInLista(exe, liste.Studio.Programmi) || Confronto.ProgrammaInLista(exe, liste.Lavoro.Programmi));
        string? titoloDaMandare = diLista ? Taglia(titolo()) : null;

        if (!copre) return new Giudizio(true, false, Modalitas.Testo(modalita), Titolo: titoloDaMandare);

        if (ÈMai(r, f.Percorso, liste)) return new Giudizio(false, true, "mai", Titolo: titoloDaMandare);
        if (exe == null) return new Giudizio(false, true, "non_riconosciuto");

        if (exe == "applicationframehost.exe")
        {
            // Regole 14: la cornice delle app dello Store solo per Calcolatrice e Strumento di cattura.
            var t = (titolo() ?? "").Trim();
            bool ok = TitoliCorniceApp.Contains(t);
            return new Giudizio(ok, !ok, ok ? "sempre" : "cornice_app", Titolo: titoloDaMandare);
        }

        if (Confronto.ProgrammaInLista(exe, liste.Sempre.Programmi)) return new Giudizio(true, false, "sempre", Titolo: titoloDaMandare);
        if (Confronto.ProgrammaInLista(exe, liste.Studio.Programmi)) return new Giudizio(true, false, "studio", Titolo: titoloDaMandare);
        if (lavoro && Confronto.ProgrammaInLista(exe, liste.Lavoro.Programmi)) return new Giudizio(true, false, "lavoro", Titolo: titoloDaMandare);
        return new Giudizio(false, true, "fuori_lista", Titolo: titoloDaMandare);
    }

    private Giudizio GiudicaBrowser(InfoFinestra f, Riconoscimento r, string? dominio, Func<string?> titolo, Liste liste, Modalita modalita,
        IReadOnlyDictionary<string, string>? verdetti, long adessoMs)
    {
        bool copre = Modalitas.Copre(modalita);
        bool lavoro = modalita == Modalita.Lavoro;
        bool mai = ÈMai(r, f.Percorso, liste);

        if (string.IsNullOrEmpty(dominio))
        {
            if (!copre) return new Giudizio(true, false, Modalitas.Testo(modalita));
            if (mai) return new Giudizio(false, true, "mai");
            // Senza dominio leggibile (scheda nuova, impostazioni, barra in uso): 20 secondi per finestra.
            Pulisci(adessoMs);
            if (!senzaDominioDal.TryGetValue(f.IdFinestra, out var dal))
            {
                dal = adessoMs;
                senzaDominioDal[f.IdFinestra] = dal;
            }
            bool ancora = adessoMs - dal < AttesaMs;
            return new Giudizio(ancora, !ancora, ancora ? "senza_dominio_attesa" : "senza_dominio");
        }

        senzaDominioDal.Remove(f.IdFinestra);
        var d = dominio.Trim().TrimEnd('.').ToLowerInvariant();
        bool daGiudicare = Confronto.SitoInLista(d, liste.DaGiudicare);
        bool sitoDiLista = daGiudicare
                           || Confronto.SitoInLista(d, liste.Studio.Siti)
                           || Confronto.SitoInLista(d, liste.Lavoro.Siti);
        string? titoloPulito = sitoDiLista ? TitoliBrowser.Pulisci(titolo()) : null;
        string? chiave = daGiudicare ? ChiaveVerdetto.Di(d, titoloPulito ?? "") : null;

        if (!copre) return new Giudizio(true, false, Modalitas.Testo(modalita), d, titoloPulito, chiave);
        if (mai || Confronto.SitoInLista(d, liste.Mai.Siti)) return new Giudizio(false, true, "mai", d, titoloPulito, chiave);

        if (daGiudicare)
        {
            string? verdetto = null;
            if (verdetti != null && chiave != null && verdetti.TryGetValue(chiave, out var v)) verdetto = v?.Trim().ToLowerInvariant();
            if (verdetto == "studio") return new Giudizio(true, false, "verdetto_studio", d, titoloPulito, chiave);
            if (verdetto == "lavoro" && lavoro) return new Giudizio(true, false, "verdetto_lavoro", d, titoloPulito, chiave);
            if (verdetto != null) return new Giudizio(false, true, "verdetto_" + verdetto, d, titoloPulito, chiave);
            Pulisci(adessoMs);
            if (!attesaVerdetto.TryGetValue(chiave!, out var dal))
            {
                dal = adessoMs;
                attesaVerdetto[chiave!] = dal;
            }
            bool ancora = adessoMs - dal < AttesaMs;
            return new Giudizio(ancora, !ancora, ancora ? "attesa_giudizio" : "senza_giudizio", d, titoloPulito, chiave);
        }

        if (Confronto.SitoInLista(d, liste.Sempre.Siti)) return new Giudizio(true, false, "sempre", d, titoloPulito);
        if (Confronto.SitoInLista(d, liste.Studio.Siti)) return new Giudizio(true, false, "studio", d, titoloPulito);
        if (lavoro && Confronto.SitoInLista(d, liste.Lavoro.Siti)) return new Giudizio(true, false, "lavoro", d, titoloPulito);
        return new Giudizio(false, true, "fuori_lista", d, titoloPulito);
    }

    /// <summary>
    /// "mai" per nome (del file, originale o riconosciuto: basta uno), o un gioco lanciato da Steam (sta nella
    /// cartella di Steam).
    /// </summary>
    private static bool ÈMai(Riconoscimento r, string? percorso, Liste liste)
    {
        foreach (var nome in new[] { r.NomeFile, r.NomeOriginale, r.Nome })
        {
            if (!string.IsNullOrEmpty(nome) && Confronto.ProgrammaInLista(nome, liste.Mai.Programmi)) return true;
        }
        if (!string.IsNullOrEmpty(percorso))
        {
            var p = percorso.Replace('/', '\\');
            if (p.Contains("\\steamapps\\", StringComparison.OrdinalIgnoreCase)
                || p.Contains("\\steam\\", StringComparison.OrdinalIgnoreCase))
                return true;
        }
        return false;
    }

    private void Pulisci(long adessoMs)
    {
        if (attesaVerdetto.Count > MassimoMemorie)
        {
            foreach (var k in attesaVerdetto.Where(kv => adessoMs - kv.Value > 3_600_000).Select(kv => kv.Key).ToList())
                attesaVerdetto.Remove(k);
            if (attesaVerdetto.Count > MassimoMemorie) attesaVerdetto.Clear();
        }
        if (senzaDominioDal.Count > MassimoMemorie) senzaDominioDal.Clear();
    }

    private static string? Taglia(string? t)
    {
        if (string.IsNullOrWhiteSpace(t)) return null;
        t = t.Trim();
        return t.Length > 300 ? t[..300] : t;
    }
}

/// <summary>La chiave dei verdetti (contratto): sha1(dominio + "|" + titolo) in esadecimale minuscolo, UTF-8.</summary>
public static class ChiaveVerdetto
{
    public static string Di(string dominio, string titolo) =>
        Convert.ToHexString(SHA1.HashData(Encoding.UTF8.GetBytes(dominio + "|" + titolo))).ToLowerInvariant();
}

/// <summary>
/// Il titolo di una pagina dal titolo della finestra del browser: senza il nome del browser, del profilo, il
/// "e altre N schede" di Edge e il "(3) " delle notifiche di YouTube. Così la stessa pagina ha sempre la
/// stessa chiave, e il NAS legge un titolo pulito.
/// </summary>
public static class TitoliBrowser
{
    private static readonly Regex Notifiche = new(@"^\(\d+\+?\)\s+", RegexOptions.Compiled);
    private static readonly Regex AltreSchede = new(
        @"\s+(e altre \d+ (schede|pagine)|e un'altra scheda|e un'altra pagina|and \d+ more (tabs?|pages?)|and 1 more (tab|page))(?=\s+-\s+|$)",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);
    private static readonly Regex Browser = new(
        @"\s+[-–—]\s+(Google Chrome|Microsoft[​\s]*Edge|Mozilla Firefox|Firefox|Brave)\s*$",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);
    private static readonly Regex Profilo = new(@"\s+-\s+(Personale|Personal|Lavoro|Work|Profilo \d+|Profile \d+|Ospite|Guest|InPrivate)\s*$",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    public static string Pulisci(string? titolo)
    {
        var t = (titolo ?? "").Replace(' ', ' ').Trim();
        for (int i = 0; i < 3; i++)
        {
            var prima = t;
            t = Browser.Replace(t, "");
            t = Profilo.Replace(t, "");
            t = AltreSchede.Replace(t, "");
            t = t.Trim();
            if (t == prima) break;
        }
        t = Notifiche.Replace(t, "");
        t = t.Trim();
        return t.Length > 300 ? t[..300] : t;
    }
}

/// <summary>
/// Le superfici di Windows che non sono "una cosa" in primo piano: barra delle applicazioni, menu Start,
/// ricerca, centro notifiche, Alt+Tab, pannello emoji, schermata di blocco. Quando sono in primo piano la
/// copertura resta com'era (decisa dall'ultima finestra vera): se no, aprire il menu Start scoprirebbe
/// il video sotto. Il desktop invece è permesso (le finestre sono nascoste).
/// </summary>
public static class SuperficiSistema
{
    private static readonly HashSet<string> ProgrammiNeutri = new(StringComparer.Ordinal)
    {
        "startmenuexperiencehost.exe", "searchhost.exe", "searchapp.exe", "shellexperiencehost.exe",
        "textinputhost.exe", "lockapp.exe", "logonui.exe", "consent.exe", "shellhost.exe",
    };

    private static readonly HashSet<string> ClassiNeutreExplorer = new(StringComparer.Ordinal)
    {
        "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland",
        "XamlExplorerHostIslandWindow", "MultitaskingViewFrame", "ForegroundStaging", "TaskListThumbnailWnd",
        "Windows.UI.Core.CoreWindow", "TaskSwitcherWnd", "TaskSwitcherOverlayWnd",
    };

    public static bool ÈNeutra(string exe, string? classe)
    {
        var e = Confronto.NormalizzaProgramma(exe);
        if (ProgrammiNeutri.Contains(e)) return true;
        return e == "explorer.exe" && classe != null && ClassiNeutreExplorer.Contains(classe);
    }
}

/// <summary>Una finestra vista sullo schermo, per capire se Pactum sta coprendo.</summary>
/// <param name="Riconosciuto">Il programma è riconosciuto (dal percorso, non solo dal nome).</param>
/// <param name="Trasparente">Finestra trasparente o che lascia passare i clic (non copre niente davvero).</param>
public readonly record struct FinestraVisibile(string Exe, bool Visibile, bool Nascosta, bool Iconica, bool SempreSopra, Rectangle Rettangolo,
    bool Riconosciuto = true, bool Trasparente = false);

/// <summary>
/// Pactum sta coprendo (Studio o lavori di casa)? Sì se una finestra di pactum.exe visibile, sempre in primo
/// piano e non nascosta copre almeno il 90% dell'area di lavoro di uno schermo (regole 12: allora la copertura
/// di Argus si fa da parte). Il pactum.exe deve essere riconosciuto (dal percorso, come gli altri programmi) e la
/// finestra non deve essere trasparente: un finto "pactum.exe" trasparente non spegne la copertura di Argus.
/// </summary>
public static class CoperturaPactum
{
    public const double SogliaCopertura = 0.9;

    public static bool Copre(IEnumerable<FinestraVisibile> finestre, IEnumerable<Rectangle> areeSchermi)
    {
        var aree = areeSchermi.Where(a => a.Width > 0 && a.Height > 0).ToList();
        foreach (var f in finestre)
        {
            if (!f.Exe.Equals("pactum.exe", StringComparison.OrdinalIgnoreCase)) continue;
            if (!f.Riconosciuto || f.Trasparente) continue;
            if (!f.Visibile || f.Nascosta || f.Iconica || !f.SempreSopra) continue;
            foreach (var a in aree)
            {
                var i = Rectangle.Intersect(a, f.Rettangolo);
                if (i.Width <= 0 || i.Height <= 0) continue;
                if ((double)i.Width * i.Height >= SogliaCopertura * a.Width * a.Height) return true;
            }
        }
        return false;
    }
}
