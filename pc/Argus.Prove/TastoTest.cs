using Argus.Nucleo;

namespace Argus.Prove;

public class TastoTest
{
    [Theory]
    [InlineData("Ctrl+Alt+T", TastoTerminale.ModCtrl | TastoTerminale.ModAlt, 0x54u, "Ctrl+Alt+T")]
    [InlineData("ctrl + alt + t", TastoTerminale.ModCtrl | TastoTerminale.ModAlt, 0x54u, "Ctrl+Alt+T")]
    [InlineData("Alt+Ctrl+A", TastoTerminale.ModCtrl | TastoTerminale.ModAlt, 0x41u, "Ctrl+Alt+A")]
    [InlineData("Ctrl+Shift+Spazio", TastoTerminale.ModCtrl | TastoTerminale.ModMaiusc, 0x20u, "Ctrl+Maiusc+Spazio")]
    [InlineData("Ctrl+Alt+Space", TastoTerminale.ModCtrl | TastoTerminale.ModAlt, 0x20u, "Ctrl+Alt+Spazio")]
    [InlineData("Win+Maiusc+5", TastoTerminale.ModWin | TastoTerminale.ModMaiusc, 0x35u, "Maiusc+Win+5")]
    [InlineData("Alt+F9", TastoTerminale.ModAlt, 0x78u, "Alt+F9")]
    [InlineData("Ctrl+F12", TastoTerminale.ModCtrl, 0x7Bu, "Ctrl+F12")]
    public void Validi(string testo, uint mod, uint vk, string mostrato)
    {
        var t = TastoTerminale.Leggi(testo);
        Assert.NotNull(t);
        Assert.Equal(mod, t!.Modificatori);
        Assert.Equal(vk, t.TastoVirtuale);
        Assert.Equal(mostrato, t.Testo);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("T")]                // senza modificatori si mangerebbe la lettera
    [InlineData("Shift+T")]          // Maiusc da solo: idem
    [InlineData("Ctrl+Alt")]         // manca il tasto
    [InlineData("Ctrl+Alt+T+Y")]     // due tasti
    [InlineData("Ctrl+Ctrl+T")]
    [InlineData("Ctrl++T")]
    [InlineData("Ctrl+Alt+Canc")]
    [InlineData("Ctrl+F25")]
    [InlineData("Ctrl+Alt+TT")]
    public void NonValidi(string? testo) => Assert.Null(TastoTerminale.Leggi(testo));

    [Fact]
    public void DiSerie_CtrlAltT()
    {
        Assert.Equal("Ctrl+Alt+T", TastoTerminale.Predefinito.Testo);
        Assert.Equal("Ctrl+Alt+T", new ConfigArgus().Tasto().Testo);
        Assert.Null(new ConfigArgus().ProblemaTasto());
    }

    [Fact]
    public void DallaConfigurazione()
    {
        var c = ConfigArgus.DaJson("""{"nas_url": "http://nas:8700", "token": "x", "tasto_terminale": "Ctrl+Alt+S"}""");
        Assert.Equal("Ctrl+Alt+S", c.Tasto().Testo);
        Assert.Null(c.ProblemaTasto());

        var rotto = ConfigArgus.DaJson("""{"nas_url": "http://nas:8700", "token": "x", "tasto_terminale": "T"}""");
        Assert.Equal("Ctrl+Alt+T", rotto.Tasto().Testo);
        Assert.Contains("non valido", rotto.ProblemaTasto());
    }

    [Fact]
    public void ConfigPerLAgente_SenzaSegretoDelloSblocco()
    {
        var c = ConfigArgus.DaJson("""
            {"nas_url": "http://nas:8700", "token": "t", "segreto_sblocco": "SEGRETO-SBLOCCO",
             "utente_controllato": "studente", "percorsi_fidati": ["C:\\App\\app.exe"]}
            """);
        Assert.Equal("SEGRETO-SBLOCCO", c.SegretoSblocco);
        var perAgente = c.PerAgente("istanza-1");
        Assert.DoesNotContain("SEGRETO-SBLOCCO", perAgente);
        Assert.DoesNotContain("segreto_sblocco\":\"", perAgente.Replace(" ", ""));
        var letta = ConfigArgus.DaJson(perAgente);
        Assert.Null(letta.SegretoSblocco);
        Assert.Equal("istanza-1", letta.Istanza);
        Assert.Equal("t", letta.Token);
        Assert.Equal(@"C:\App\app.exe", Assert.Single(letta.PercorsiFidati));
        Assert.Equal("SEGRETO-SBLOCCO", c.SegretoSblocco); // l'originale non cambia
    }

    [Fact]
    public void TestoDellaCopertura()
    {
        Assert.Equal("Torna a una cosa permessa o apri il terminale: Ctrl+Alt+T", Testi.SecondaRigaCopertura("Ctrl+Alt+T"));
        Assert.Equal("Torna a una cosa permessa o apri il terminale: fai clic qui.", Testi.SecondaRigaCoperturaSenzaTasto);
    }
}
