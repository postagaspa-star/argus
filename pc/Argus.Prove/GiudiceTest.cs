using System.Drawing;
using Argus.Nucleo;

namespace Argus.Prove;

public class GiudiceTest
{
    private static readonly Liste L = Liste.Iniziali();
    private static readonly Func<string?> SenzaTitolo = () => null;

    private static Giudizio G(GiudiceFinestra g, string exe, Modalita m, string? dominio = null, string? titolo = null,
        IReadOnlyDictionary<string, string>? verdetti = null, long ms = 0, long finestra = 1, string? percorso = null, Liste? liste = null) =>
        g.Giudica(new InfoFinestra(finestra, exe, percorso, R(exe)), dominio, () => titolo, liste ?? L, m, verdetti, ms);

    /// <summary>Nelle prove del giudice i programmi sono già riconosciuti (come se stessero in Program Files).</summary>
    internal static Riconoscimento R(string exe) =>
        GiudiceFinestra.ProgrammiArgus.Contains(exe.ToLowerInvariant())
            ? new Riconoscimento(exe.ToLowerInvariant(), exe.ToLowerInvariant(), ComeRiconosciuto.Argus)
            : Riconoscimento.DalNome(exe);

    [Fact]
    public void LiberoEInattivo_NienteCopertura()
    {
        var g = new GiudiceFinestra();
        Assert.False(G(g, "steam.exe", Modalita.Libero).DaCoprire);
        Assert.False(G(g, "steam.exe", Modalita.Inattivo).DaCoprire);
        Assert.False(G(g, "chrome.exe", Modalita.Libero, "instagram.com").DaCoprire);
        Assert.True(G(g, "steam.exe", Modalita.Libero).Permesso);
    }

    [Theory]
    [InlineData("explorer.exe", Modalita.Studio, true)]
    [InlineData("notepad.exe", Modalita.Studio, true)]
    [InlineData("soffice.exe", Modalita.Studio, true)]
    [InlineData("lectio.exe", Modalita.Studio, true)]
    [InlineData("claude.exe", Modalita.Studio, false)]
    [InlineData("claude.exe", Modalita.Lavoro, true)]
    [InlineData("wisper ufficio.exe", Modalita.Lavoro, true)]
    [InlineData("soffice.exe", Modalita.Lavoro, true)]
    [InlineData("spotify.exe", Modalita.Studio, false)]
    [InlineData("spotify.exe", Modalita.Lavoro, false)]
    [InlineData("steam.exe", Modalita.Lavoro, false)]
    [InlineData("minecraftlauncher.exe", Modalita.Studio, false)]
    [InlineData("whatsapp.exe", Modalita.Lavoro, false)]
    [InlineData("argus.agente.exe", Modalita.Studio, true)]
    public void Programmi(string exe, Modalita m, bool permesso)
    {
        var r = G(new GiudiceFinestra(), exe, m);
        Assert.Equal(permesso, r.Permesso);
        Assert.Equal(!permesso, r.DaCoprire);
    }

    [Fact]
    public void ProgrammiDiArgus_SempreAncheConListeVuote()
    {
        var vuote = new Liste();
        Assert.True(G(new GiudiceFinestra(), "argus.agente.exe", Modalita.Studio, liste: vuote).Permesso);
        Assert.True(G(new GiudiceFinestra(), "argus.sblocco.exe", Modalita.Studio, liste: vuote).Permesso);
        Assert.False(G(new GiudiceFinestra(), "notepad.exe", Modalita.Studio, liste: vuote).Permesso);
    }

    [Fact]
    public void MaiVinceAncheSeAggiunto()
    {
        var l = Liste.Iniziali();
        l.Studio.Programmi.Add("steam.exe");
        l.Sempre.Siti.Add("instagram.com");
        Assert.Equal("mai", G(new GiudiceFinestra(), "steam.exe", Modalita.Studio, liste: l).Motivo);
        Assert.Equal("mai", G(new GiudiceFinestra(), "chrome.exe", Modalita.Studio, "www.instagram.com", liste: l).Motivo);
    }

    [Fact]
    public void GiochiLanciatiDaSteam_Mai()
    {
        var l = Liste.Iniziali();
        l.Studio.Programmi.Add("gioco.exe");
        var r = G(new GiudiceFinestra(), "gioco.exe", Modalita.Studio, percorso: @"D:\Giochi\Steam\steamapps\common\Gioco\gioco.exe", liste: l);
        Assert.True(r.DaCoprire);
        Assert.Equal("mai", r.Motivo);
    }

    [Theory]
    [InlineData("Calcolatrice", true)]
    [InlineData("Strumento di cattura", true)]
    [InlineData("Impostazioni", false)]
    [InlineData("Xbox", false)]
    public void CorniceDelleApp(string titolo, bool permesso) =>
        Assert.Equal(permesso, G(new GiudiceFinestra(), "applicationframehost.exe", Modalita.Studio, titolo: titolo).Permesso);

    [Theory]
    [InlineData("it.wikipedia.org", Modalita.Studio, true)]
    [InlineData("docs.google.com", Modalita.Studio, true)]
    [InlineData("github.com", Modalita.Studio, false)]
    [InlineData("github.com", Modalita.Lavoro, true)]
    [InlineData("192.168.0.20", Modalita.Lavoro, true)]
    [InlineData("192.168.0.20", Modalita.Studio, false)]
    [InlineData("localhost", Modalita.Lavoro, true)]
    [InlineData("www.instagram.com", Modalita.Lavoro, false)]
    [InlineData("web.whatsapp.com", Modalita.Lavoro, false)]
    [InlineData("www.amazon.it", Modalita.Studio, false)]
    public void Siti(string dominio, Modalita m, bool permesso)
    {
        var r = G(new GiudiceFinestra(), "chrome.exe", m, dominio, "Pagina");
        Assert.Equal(permesso, r.Permesso);
        Assert.Equal(!permesso, r.DaCoprire);
        Assert.Equal(dominio, r.Dominio);
    }

    [Fact]
    public void BrowserSenzaDominio_20SecondiPerFinestra()
    {
        var g = new GiudiceFinestra();
        Assert.True(G(g, "chrome.exe", Modalita.Studio, null, ms: 0, finestra: 7).Permesso);
        Assert.True(G(g, "chrome.exe", Modalita.Studio, null, ms: 19_999, finestra: 7).Permesso);
        var r = G(g, "chrome.exe", Modalita.Studio, null, ms: 20_000, finestra: 7);
        Assert.False(r.Permesso);
        Assert.True(r.DaCoprire);
        Assert.Equal("senza_dominio", r.Motivo);
        // Cambiare finestra e tornare non fa ripartire i 20 secondi.
        Assert.True(G(g, "msedge.exe", Modalita.Studio, null, ms: 21_000, finestra: 8).Permesso);
        Assert.True(G(g, "chrome.exe", Modalita.Studio, null, ms: 22_000, finestra: 7).DaCoprire);
        // Un dominio letto in quella finestra li azzera.
        Assert.True(G(g, "chrome.exe", Modalita.Studio, "it.wikipedia.org", "Storia", ms: 23_000, finestra: 7).Permesso);
        Assert.True(G(g, "chrome.exe", Modalita.Studio, null, ms: 24_000, finestra: 7).Permesso);
    }

    [Fact]
    public void SitoDaGiudicare_AttesaPoiCoperto()
    {
        var g = new GiudiceFinestra();
        const string titolo = "Rivoluzione francese spiegata facile - YouTube - Google Chrome";
        var r = G(g, "chrome.exe", Modalita.Studio, "youtube.com", titolo, ms: 0);
        Assert.True(r.Permesso);
        Assert.Equal("attesa_giudizio", r.Motivo);
        Assert.Equal("Rivoluzione francese spiegata facile - YouTube", r.Titolo);
        Assert.Equal("bbfbe152f12cc352f1409729a818d464dc16a911", r.Chiave);
        Assert.True(G(g, "chrome.exe", Modalita.Studio, "youtube.com", titolo, ms: 19_000).Permesso);
        Assert.True(G(g, "chrome.exe", Modalita.Studio, "youtube.com", titolo, ms: 20_000).DaCoprire);
        // Arriva il verdetto: studio.
        var v = new Dictionary<string, string> { [r.Chiave!] = "studio" };
        Assert.True(G(g, "chrome.exe", Modalita.Studio, "youtube.com", titolo, v, ms: 25_000).Permesso);
    }

    [Theory]
    [InlineData("svago", Modalita.Studio, false)]
    [InlineData("non_si_capisce", Modalita.Studio, false)]
    [InlineData("lavoro", Modalita.Studio, false)]
    [InlineData("lavoro", Modalita.Lavoro, true)]
    [InlineData("studio", Modalita.Lavoro, true)]
    [InlineData("STUDIO", Modalita.Studio, true)]
    public void VerdettiSubito(string verdetto, Modalita m, bool permesso)
    {
        var chiave = ChiaveVerdetto.Di("www.youtube.com", "Lezione di storia - YouTube");
        Assert.Equal("759ce896cc2f047667242de95180f66e435ea8ad", chiave);
        var v = new Dictionary<string, string> { [chiave] = verdetto };
        var r = G(new GiudiceFinestra(), "msedge.exe", m, "www.youtube.com", "Lezione di storia - YouTube e altre 2 schede - Personale - Microsoft\u200bEdge", v, ms: 0);
        Assert.Equal(chiave, r.Chiave);
        Assert.Equal(permesso, r.Permesso);
    }

    [Fact]
    public void ChiaveConLettereAccentate() =>
        Assert.Equal("ef52cd1a964fe3bebbc0e0d6167b56e75835e234", ChiaveVerdetto.Di("claude.ai", "Città d'arte"));

    [Fact]
    public void TitoloSoloQuandoServe()
    {
        var g = new GiudiceFinestra();
        int letture = 0;
        string? Titolo() { letture++; return "Segreto"; }
        // Programma fuori lista: il titolo non si legge nemmeno.
        var r1 = g.Giudica(new InfoFinestra(1, "spotify.exe", null, R("spotify.exe")), null, Titolo, L, Modalita.Studio, null, 0);
        Assert.Null(r1.Titolo);
        Assert.Equal(0, letture);
        // Sito fuori lista: nemmeno.
        var r2 = g.Giudica(new InfoFinestra(1, "chrome.exe", null, R("chrome.exe")), "www.amazon.it", Titolo, L, Modalita.Studio, null, 0);
        Assert.Null(r2.Titolo);
        Assert.Equal(0, letture);
        // Programma di studio: sì (serve al diario).
        var r3 = g.Giudica(new InfoFinestra(1, "soffice.exe", null, R("soffice.exe")), null, Titolo, L, Modalita.Studio, null, 0);
        Assert.Equal("Segreto", r3.Titolo);
        // Sito di studio: sì.
        var r4 = g.Giudica(new InfoFinestra(1, "chrome.exe", null, R("chrome.exe")), "it.wikipedia.org", Titolo, L, Modalita.Libero, null, 0);
        Assert.Equal("Segreto", r4.Titolo);
        // "sempre": no.
        var r5 = g.Giudica(new InfoFinestra(1, "notepad.exe", null, R("notepad.exe")), null, () => "appunti.txt", L, Modalita.Studio, null, 0);
        Assert.Null(r5.Titolo);
    }
}

public class TitoliBrowserTest
{
    [Theory]
    [InlineData("Rivoluzione francese - Wikipedia - Google Chrome", "Rivoluzione francese - Wikipedia")]
    [InlineData("Rivoluzione francese - Wikipedia — Mozilla Firefox", "Rivoluzione francese - Wikipedia")]
    [InlineData("Video - YouTube - Personale - Microsoft\u200bEdge", "Video - YouTube")]
    [InlineData("Video - YouTube e altre 3 schede - Personale - Microsoft Edge", "Video - YouTube")]
    [InlineData("Video - YouTube and 2 more pages - Profile 1 - Microsoft Edge", "Video - YouTube")]
    [InlineData("(3) Lezione di storia - YouTube - Brave", "Lezione di storia - YouTube")]
    [InlineData("Claude", "Claude")]
    [InlineData("", "")]
    public void Pulisce(string grezzo, string atteso) => Assert.Equal(atteso, TitoliBrowser.Pulisci(grezzo));
}

public class SuperficiETestTest
{
    [Theory]
    [InlineData("explorer.exe", "Shell_TrayWnd", true)]
    [InlineData("explorer.exe", "CabinetWClass", false)]
    [InlineData("explorer.exe", "Progman", false)]
    [InlineData("startmenuexperiencehost.exe", null, true)]
    [InlineData("SearchHost.exe", "Windows.UI.Core.CoreWindow", true)]
    [InlineData("chrome.exe", "Shell_TrayWnd", false)]
    public void SuperficiNeutre(string exe, string? classe, bool neutra) => Assert.Equal(neutra, SuperficiSistema.ÈNeutra(exe, classe));

    [Fact]
    public void CoperturaDiPactum()
    {
        var schermo = new Rectangle(0, 0, 1920, 1040);
        var studio = new FinestraVisibile("pactum.exe", true, false, false, true, new Rectangle(0, 0, 1920, 1040));
        var lavori = new FinestraVisibile("Pactum.exe", true, false, false, true, new Rectangle(0, 0, 1920, 1080));
        Assert.True(CoperturaPactum.Copre(new[] { studio }, new[] { schermo }));
        Assert.True(CoperturaPactum.Copre(new[] { lavori }, new[] { schermo }));
        Assert.False(CoperturaPactum.Copre(new[] { studio with { Exe = "chrome.exe" } }, new[] { schermo }));
        Assert.False(CoperturaPactum.Copre(new[] { studio with { SempreSopra = false } }, new[] { schermo }));
        Assert.False(CoperturaPactum.Copre(new[] { studio with { Nascosta = true } }, new[] { schermo }));
        Assert.False(CoperturaPactum.Copre(new[] { studio with { Rettangolo = new Rectangle(100, 100, 800, 600) } }, new[] { schermo }));
        // Su un secondo schermo.
        var secondo = new Rectangle(1920, 0, 1280, 1024);
        Assert.True(CoperturaPactum.Copre(new[] { studio with { Rettangolo = secondo } }, new[] { schermo, secondo }));
    }

    [Fact]
    public void ComandiSenzaNas()
    {
        Assert.Equal(Testi.NasNonRisponde, ComandiLocali.Rispondi("ps m: bagno & t: 10", null));
        Assert.Equal("Il NAS non risponde: riprova tra poco.", ComandiLocali.Rispondi("lv30", null));
        Assert.Contains("ps m: <motivo>", ComandiLocali.Rispondi(" AIUTO ", null));
        var st = ComandiLocali.Rispondi("st", new ModalitaEffettiva(Modalita.Studio, "senza_nas", true, null));
        Assert.Contains("modalità studio", st);
        Assert.Equal(11, Testi.Aiuto.Split('\n').Length);
    }

    [Fact]
    public void CodaDeiCampioni()
    {
        var c = new CodaCampioni();
        for (int i = 0; i < 40; i++) c.Aggiungi(new Campione { Ts = i.ToString() });
        Assert.Equal(30, c.Quanti);
        var presi = c.Preleva();
        Assert.Equal("10", presi[0].Ts);
        Assert.Equal("39", presi[^1].Ts);
        Assert.Equal(0, c.Quanti);
        c.Aggiungi(new Campione { Ts = "40" });
        c.Rimetti(presi);
        var di_nuovo = c.Preleva();
        Assert.Equal(30, di_nuovo.Count);
        Assert.Equal("11", di_nuovo[0].Ts);
        Assert.Equal("40", di_nuovo[^1].Ts);
    }
}
