using Argus.Nucleo;

namespace Argus.Prove;

public class ConfrontoTest
{
    [Theory]
    [InlineData("chrome.exe", "chrome.exe", true)]
    [InlineData("Chrome.EXE", "chrome.exe", true)]
    [InlineData("chrome.exe", "Chrome.exe", true)]
    [InlineData("chromex.exe", "chrome.exe", false)]
    [InlineData("wisper ufficio.exe", "wisper ufficio", true)]
    [InlineData("wisper ufficio 1.2.exe", "wisper ufficio", true)]
    [InlineData("wisper.exe", "wisper ufficio", false)]
    [InlineData("lectio.exe", "lectio", true)]
    [InlineData("lectio-pc.exe", "lectio", true)]
    [InlineData("minecraftlauncher.exe", "minecraft", true)]
    [InlineData("minecraft.windows.exe", "minecraft", true)]
    [InlineData("xboxpcapp.exe", "xbox", true)]
    [InlineData("steamwebhelper.exe", "steam.exe", false)]
    [InlineData("notepad.exe", "notepad", true)]
    [InlineData("notepad++.exe", "notepad.exe", false)]
    public void Programmi(string exe, string voce, bool atteso) =>
        Assert.Equal(atteso, Confronto.ProgrammaInLista(exe, new[] { voce }));

    [Theory]
    [InlineData("wikipedia.org", "wikipedia.org", true)]
    [InlineData("it.wikipedia.org", "wikipedia.org", true)]
    [InlineData("it.m.wikipedia.org", "wikipedia.org", true)]
    [InlineData("notwikipedia.org", "wikipedia.org", false)]
    [InlineData("wikipedia.org.evil.com", "wikipedia.org", false)]
    [InlineData("IT.Wikipedia.ORG.", "wikipedia.org", true)]
    [InlineData("docs.google.com", "docs.google.com", true)]
    [InlineData("google.com", "docs.google.com", false)]
    [InlineData("mail.google.com", "docs.google.com", false)]
    [InlineData("192.168.0.20", "192.168.", true)]
    [InlineData("192.168.0.1", "192.168.", true)]
    [InlineData("192.169.1.1", "192.168.", false)]
    [InlineData("192.168.evil.com", "192.168.", false)]
    [InlineData("localhost", "localhost", true)]
    [InlineData("evil.localhost", "localhost", false)]
    [InlineData("127.0.0.1", "127.0.0.1", true)]
    [InlineData("127.0.0.2", "127.0.0.1", false)]
    [InlineData("web.whatsapp.com", "web.whatsapp.com", true)]
    [InlineData("whatsapp.com", "web.whatsapp.com", false)]
    [InlineData("x.com", "x.com", true)]
    [InlineData("max.com", "x.com", false)]
    [InlineData("www.youtube.com", "https://www.youtube.com/", true)]
    [InlineData("youtube.com", "www.youtube.com", true)] // "www." non conta (Chrome lo nasconde)
    [InlineData("youtube.com", "m.youtube.com", false)]
    [InlineData("m.youtube.com", "youtube.com", true)]
    public void Siti(string dominio, string voce, bool atteso) =>
        Assert.Equal(atteso, Confronto.SitoInLista(dominio, new[] { voce }));

    [Theory]
    [InlineData("https://Wikipedia.org/wiki/x", "wikipedia.org")]
    [InlineData("*.netlify.app", "netlify.app")]
    [InlineData("localhost:8700", "localhost")]
    [InlineData("192.168.", "192.168.")]
    [InlineData("  Esempio.EU  ", "esempio.eu")]
    public void NormalizzaVoce(string voce, string atteso) => Assert.Equal(atteso, Confronto.NormalizzaVoceSito(voce));
}

public class IndirizziTest
{
    [Theory]
    [InlineData("https://it.wikipedia.org/wiki/Rivoluzione_francese", "it.wikipedia.org")]
    [InlineData("it.wikipedia.org/wiki/Rivoluzione_francese", "it.wikipedia.org")]
    [InlineData("www.youtube.com/watch?v=abc", "youtube.com")]
    [InlineData("HTTPS://WWW.YOUTUBE.COM", "youtube.com")]
    [InlineData("www.com", "www.com")]
    [InlineData("www2.example.com", "www2.example.com")]
    [InlineData("localhost:8700/api", "localhost")]
    [InlineData("http://127.0.0.1:8781/health", "127.0.0.1")]
    [InlineData("192.168.0.20:8700", "192.168.0.20")]
    [InlineData("http://user:pass@example.com/", "example.com")]
    [InlineData("claude.ai/new", "claude.ai")]
    public void SitiLetti(string barra, string atteso) => Assert.Equal(atteso, Indirizzi.HostDaBarra(barra));

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("rivoluzione francese")]
    [InlineData("cerca")]
    [InlineData("about:blank")]
    [InlineData("chrome://settings")]
    [InlineData("edge://newtab")]
    [InlineData("file:///C:/Users/x/doc.pdf")]
    [InlineData("view-source:https://example.com")]
    [InlineData("chrome-extension://abcdef/popup.html")]
    [InlineData("javascript:alert(1)")]
    [InlineData("ms-settings:display")]
    public void NienteSito(string? barra) => Assert.Null(Indirizzi.HostDaBarra(barra));
}

public class ListeTest
{
    [Fact]
    public void LeggeIlJsonDelContratto()
    {
        var json = """
        {
          "versione": 7,
          "sempre":  {"programmi": ["Explorer.exe"], "siti": []},
          "studio":  {"programmi": ["soffice.exe"], "siti": ["https://Wikipedia.org/"]},
          "lavoro":  {"programmi": ["claude.exe"], "siti": ["github.com"]},
          "da_giudicare": ["youtube.com", "claude.ai"],
          "mai":     {"programmi": ["steam.exe"], "siti": ["instagram.com"]},
          "browser": ["chrome.exe", "msedge.exe"]
        }
        """;
        var l = Liste.DaJson(json);
        Assert.Equal(7, l.Versione);
        Assert.Contains("explorer.exe", l.Sempre.Programmi);
        Assert.Contains("wikipedia.org", l.Studio.Siti);
        Assert.Equal(new[] { "youtube.com", "claude.ai" }, l.DaGiudicare);
        Assert.True(l.ÈBrowser("Chrome.exe"));
        Assert.False(l.ÈBrowser("firefox.exe"));
    }

    [Fact]
    public void ListeInizialiDelleRegole()
    {
        var l = Liste.Iniziali();
        Assert.Equal(0, l.Versione);
        Assert.Contains("explorer.exe", l.Sempre.Programmi);
        Assert.Contains("wikipedia.org", l.Studio.Siti);
        Assert.Contains("192.168.", l.Lavoro.Siti);
        Assert.Contains("youtube.com", l.DaGiudicare);
        Assert.Contains("steam.exe", l.Mai.Programmi);
        Assert.Contains("instagram.com", l.Mai.Siti);
        Assert.Equal(4, l.Browser.Count);
    }

    [Fact]
    public void GruppiMancantiDiventanoVuoti()
    {
        var l = Liste.DaJson("{\"versione\": 3}");
        Assert.Empty(l.Sempre.Programmi);
        Assert.Empty(l.Mai.Siti);
        Assert.Empty(l.Browser);
    }
}
