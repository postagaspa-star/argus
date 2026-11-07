using System.Drawing;
using Argus.Nucleo;

namespace Argus.Prove;

/// <summary>Programmi riconosciuti dal percorso, non solo dal nome (revisione B5).</summary>
public class RiconoscimentoTest
{
    private const string Pf = @"C:\Program Files";
    private const string Pf86 = @"C:\Program Files (x86)";
    private const string Win = @"C:\Windows";
    private const string Argus = @"C:\Program Files\Argus";
    private const string Utente = @"C:\Users\studente";

    private sealed class FileFinti : ISistemaFile
    {
        public readonly Dictionary<string, (bool Scrivibile, bool Firma, string? Originale, DateTime Modifica)> File = new(StringComparer.OrdinalIgnoreCase);
        public int FirmeControllate;

        public FileFinti Con(string percorso, bool scrivibile = false, bool firma = false, string? originale = null)
        {
            File[percorso] = (scrivibile, firma, originale, new DateTime(2026, 11, 1));
            return this;
        }

        public (DateTime Modifica, long Byte)? Impronta(string p) => File.TryGetValue(p, out var f) ? (f.Modifica, 1000) : null;
        public bool Scrivibile(string p) => !File.TryGetValue(p, out var f) || f.Scrivibile;

        public bool FirmaValida(string p)
        {
            FirmeControllate++;
            return File.TryGetValue(p, out var f) && f.Firma;
        }

        public string? NomeOriginale(string p) => File.TryGetValue(p, out var f) ? f.Originale : null;
    }

    private static RiconoscitoreProgrammi Nuovo(FileFinti fs, params string[] fidati) =>
        new(fs, new[] { Pf, Pf86, Win }, Argus, fidati);

    [Fact]
    public void Argus_SoloDallaSuaCartella()
    {
        var fs = new FileFinti()
            .Con(Argus + @"\Argus.Agente.exe")
            .Con(Utente + @"\Downloads\Argus.Agente.exe")
            .Con(Pf + @"\Altro\argus.sblocco.exe")
            .Con(Pf + @"\Giochi\argusgioco.exe");
        var r = Nuovo(fs);
        Assert.Equal(ComeRiconosciuto.Argus, r.Riconosci("argus.agente.exe", Argus + @"\Argus.Agente.exe").Come);
        Assert.Null(r.Riconosci("argus.agente.exe", Utente + @"\Downloads\Argus.Agente.exe").Nome);
        Assert.Null(r.Riconosci("argus.sblocco.exe", Pf + @"\Altro\argus.sblocco.exe").Nome);
        Assert.Null(r.Riconosci("argusgioco.exe", Pf + @"\Giochi\argusgioco.exe").Nome); // la voce "argus" del NAS non basta
    }

    [Fact]
    public void ProgramFiles_BastaIlNome()
    {
        var fs = new FileFinti().Con(Pf + @"\LibreOffice\program\soffice.exe").Con(Pf86 + @"\Microsoft\Edge\Application\msedge.exe")
            .Con(Win + @"\System32\notepad.exe");
        var r = Nuovo(fs);
        var lo = r.Riconosci("soffice.exe", Pf + @"\LibreOffice\program\soffice.exe");
        Assert.Equal(("soffice.exe", ComeRiconosciuto.CartellaProtetta), (lo.Nome, lo.Come));
        Assert.Equal("msedge.exe", r.Riconosci("msedge.exe", Pf86 + @"\Microsoft\Edge\Application\msedge.exe").Nome);
        Assert.Equal("notepad.exe", r.Riconosci("notepad.exe", Win + @"\System32\notepad.exe").Nome);
        Assert.Equal(0, fs.FirmeControllate); // in cartella protetta la firma non serve
    }

    [Fact]
    public void CartellaDiSistemaMaScrivibile_ServeLaFirma()
    {
        // Per esempio Windows\Temp, o un programma installato male con "Users: controllo completo".
        var fs = new FileFinti().Con(Win + @"\Temp\soffice.exe", scrivibile: true);
        var r = Nuovo(fs).Riconosci("soffice.exe", Win + @"\Temp\soffice.exe");
        Assert.Null(r.Nome);
        Assert.Equal(ComeRiconosciuto.NonRiconosciuto, r.Come);
    }

    [Fact]
    public void GiocoRinominato_NonVale()
    {
        var gioco = Utente + @"\Downloads\gioco\soffice.exe";
        var fs = new FileFinti().Con(gioco, scrivibile: true, firma: false, originale: "Gioco.exe");
        var r = Nuovo(fs).Riconosci("soffice.exe", gioco);
        Assert.Null(r.Nome);
        Assert.Equal("gioco.exe", r.NomeOriginale);
        var g = new GiudiceFinestra().Giudica(new InfoFinestra(1, "soffice.exe", gioco, r), null, () => "Gioco", Liste.Iniziali(), Modalita.Studio, null, 0);
        Assert.True(g.DaCoprire);
        Assert.Equal("non_riconosciuto", g.Motivo);
        Assert.Null(g.Titolo); // il titolo di un programma non riconosciuto non va al NAS
    }

    [Fact]
    public void ChromiumPortatileRinominato_NonEUnBrowser()
    {
        var chromium = Utente + @"\Desktop\chrome-win\chrome.exe";
        var fs = new FileFinti().Con(chromium, scrivibile: true, firma: false, originale: "chrome.exe");
        var r = Nuovo(fs).Riconosci("chrome.exe", chromium);
        Assert.Null(r.Nome);
        var g = new GiudiceFinestra().Giudica(new InfoFinestra(1, "chrome.exe", chromium, r), "it.wikipedia.org", () => "Wikipedia",
            Liste.Iniziali(), Modalita.Studio, null, 0);
        Assert.True(g.DaCoprire); // senza firma non vale nemmeno su un sito di studio
        Assert.Equal("non_riconosciuto", g.Motivo);
    }

    [Fact]
    public void FirmaValida_ValeIlNomeOriginale()
    {
        var python = Utente + @"\AppData\Local\Programs\Python\Python314\python.exe";
        var rinominato = Utente + @"\Downloads\soffice.exe";
        var senzaNome = Utente + @"\AppData\Local\App\app.exe";
        var fs = new FileFinti()
            .Con(python, scrivibile: true, firma: true, originale: "py.exe")
            .Con(rinominato, scrivibile: true, firma: true, originale: "Steam.exe")
            .Con(senzaNome, scrivibile: true, firma: true, originale: null);
        var r = Nuovo(fs);
        var p = r.Riconosci("python.exe", python);
        Assert.Equal(("py.exe", ComeRiconosciuto.Firma), (p.Nome, p.Come));
        var s = r.Riconosci("soffice.exe", rinominato);
        Assert.Equal("steam.exe", s.Nome); // vale il nome scritto nel file, non quello del file
        var g = new GiudiceFinestra().Giudica(new InfoFinestra(1, "soffice.exe", rinominato, s), null, () => "", Liste.Iniziali(), Modalita.Studio, null, 0);
        Assert.Equal("mai", g.Motivo);
        Assert.Null(r.Riconosci("app.exe", senzaNome).Nome); // firmato ma senza nome originale
    }

    [Fact]
    public void FirmaValida_NomeOriginaleNellaLista()
    {
        var py = Utente + @"\AppData\Local\Programs\Python\Python314\python.exe";
        var fs = new FileFinti().Con(py, scrivibile: true, firma: true, originale: "python.exe");
        var r = Nuovo(fs).Riconosci("python.exe", py);
        var g = new GiudiceFinestra().Giudica(new InfoFinestra(1, "python.exe", py, r), null, () => "Python", Liste.Iniziali(), Modalita.Lavoro, null, 0);
        Assert.True(g.Permesso);
        Assert.Equal("lavoro", g.Motivo);
    }

    [Fact]
    public void PercorsiFidati()
    {
        var lectio = Utente + @"\AppData\Local\Lectio\Lectio.exe";
        var altra = Utente + @"\AppData\Local\Lectio2\Lectio.exe";
        var fs = new FileFinti().Con(lectio, scrivibile: true).Con(altra, scrivibile: true);
        var r = Nuovo(fs, @"c:/users/STUDENTE/appdata/local/lectio/lectio.exe");
        var l = r.Riconosci("lectio.exe", lectio);
        Assert.Equal(("lectio.exe", ComeRiconosciuto.PercorsoFidato), (l.Nome, l.Come));
        Assert.Null(r.Riconosci("lectio.exe", altra).Nome); // stesso nome, altra cartella: no
        var g = new GiudiceFinestra().Giudica(new InfoFinestra(1, "lectio.exe", lectio, l), null, () => "Lezione", Liste.Iniziali(), Modalita.Studio, null, 0);
        Assert.Equal("studio", g.Motivo);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData(@"gioco\soffice.exe")]
    public void SenzaPercorsoCompleto_NonRiconosciuto(string? percorso)
    {
        var r = Nuovo(new FileFinti()).Riconosci("soffice.exe", percorso);
        Assert.Equal(ComeRiconosciuto.SenzaPercorso, r.Come);
        Assert.Null(r.Nome);
    }

    [Fact]
    public void PrefissoLungo_Accettato()
    {
        var fs = new FileFinti().Con(Pf + @"\LibreOffice\program\soffice.exe");
        Assert.Equal("soffice.exe", Nuovo(fs).Riconosci(null, @"\\?\C:\Program Files\LibreOffice\program\soffice.exe").Nome);
    }

    [Fact]
    public void Memoria_PerPercorsoEData()
    {
        var p = Utente + @"\AppData\Local\Programs\App\app.exe";
        var fs = new FileFinti().Con(p, scrivibile: true, firma: true, originale: "app.exe");
        var r = Nuovo(fs);
        for (int i = 0; i < 10; i++) Assert.Equal("app.exe", r.Riconosci("app.exe", p).Nome);
        Assert.Equal(1, fs.FirmeControllate); // controllata una volta sola
        fs.File[p] = (true, false, "app.exe", new DateTime(2026, 11, 2)); // file cambiato: firma non più valida
        Assert.Null(r.Riconosci("app.exe", p).Nome);
        Assert.Equal(2, fs.FirmeControllate);
    }

    [Fact]
    public void NomePerIlNas()
    {
        var l = Liste.Iniziali();
        Assert.Equal("soffice.exe", Riconoscimento.DalNome("soffice.exe").NomePerNas(l));
        Assert.Equal("non_riconosciuto:soffice.exe", new Riconoscimento("soffice.exe", null, ComeRiconosciuto.NonRiconosciuto).NomePerNas(l));
        Assert.Equal("steam.exe", new Riconoscimento("steam.exe", null, ComeRiconosciuto.NonRiconosciuto).NomePerNas(l));
        Assert.Equal("minecraft.exe", new Riconoscimento("notepad.exe", null, ComeRiconosciuto.NonRiconosciuto, "minecraft.exe").NomePerNas(l));
        Assert.Equal("", new Riconoscimento("", null, ComeRiconosciuto.SenzaPercorso).NomePerNas(l));
    }

    [Fact]
    public void MaiColNomeOriginale_AncheSenzaFirma()
    {
        var finto = Utente + @"\Downloads\notepad.exe";
        var fs = new FileFinti().Con(finto, scrivibile: true, firma: false, originale: "Minecraft.exe");
        var r = Nuovo(fs).Riconosci("notepad.exe", finto);
        var g = new GiudiceFinestra().Giudica(new InfoFinestra(1, "notepad.exe", finto, r), null, () => "", Liste.Iniziali(), Modalita.Studio, null, 0);
        Assert.Equal("mai", g.Motivo);
    }

    [Fact]
    public void GiudiceSenzaRiconoscimento_NonVale()
    {
        // Chi chiama il giudice senza riconoscimento non ottiene il vecchio "basta il nome".
        var g = new GiudiceFinestra().Giudica(new InfoFinestra(1, "soffice.exe"), null, () => "", Liste.Iniziali(), Modalita.Studio, null, 0);
        Assert.True(g.DaCoprire);
        Assert.Equal("non_riconosciuto", g.Motivo);
    }

    [Fact]
    public void PactumFintoOTrasparente_NonCopre()
    {
        var schermo = new[] { new Rectangle(0, 0, 1920, 1040) };
        var vera = new FinestraVisibile("pactum.exe", true, false, false, true, new Rectangle(0, 0, 1920, 1080));
        Assert.True(CoperturaPactum.Copre(new[] { vera }, schermo));
        Assert.False(CoperturaPactum.Copre(new[] { vera with { Riconosciuto = false } }, schermo));
        Assert.False(CoperturaPactum.Copre(new[] { vera with { Trasparente = true } }, schermo));
    }
}
