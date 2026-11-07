using System.Text.Json.Nodes;
using Argus.Nucleo;

namespace Argus.Prove;

public class CondizioniTest
{
    private const long GB = 1024L * 1024 * 1024;

    /// <summary>Un minuto di misure ogni 5 secondi con il processore occupato come detto.</summary>
    private static (CondizioniModello C, long Ms) Minuto(double occupato, double motore = 0, int secondi = 60)
    {
        var c = new CondizioniModello();
        long ms = 0;
        for (int s = 5; s <= secondi; s += 5)
        {
            ms = s * 1000L;
            long totale = 5_000_000 * 8; // 5 secondi su 8 processori, unità da 100 ns
            c.AggiungiCpu(ms, totale, (long)(totale * (1 - occupato)), (long)(totale * motore));
        }
        return (c, ms);
    }

    [Fact]
    public void TuttoBene()
    {
        var (c, ms) = Minuto(0.2);
        var v = c.Valuta(ms, true, true, 12 * GB, 0);
        Assert.True(v.Valide, v.Motivo);
    }

    [Fact]
    public void ABatteriaNo()
    {
        var (c, ms) = Minuto(0.1);
        Assert.False(c.Valuta(ms, false, true, 12 * GB, 0).Valide);
        Assert.False(c.Valuta(ms, null, true, 12 * GB, 0).Valide); // sconosciuto con batteria: no
        Assert.True(c.Valuta(ms, null, false, 12 * GB, 0).Valide);  // fisso senza batteria: sì
        Assert.Contains("batteria", c.Valuta(ms, false, true, 12 * GB, 0).Motivo);
    }

    [Fact]
    public void PocaMemoriaNo_MaQuellaDelMotoreConta()
    {
        var (c, ms) = Minuto(0.1);
        Assert.False(c.Valuta(ms, true, true, 7 * GB, 0).Valide);
        Assert.True(c.Valuta(ms, true, true, 3 * GB, 6 * GB).Valide); // il motore acceso non si spegne da solo
        Assert.Contains("memoria", c.Valuta(ms, true, true, 7 * GB, 0).Motivo);
    }

    [Fact]
    public void ProcessoreOccupatoNo()
    {
        var (c, ms) = Minuto(0.55);
        var v = c.Valuta(ms, true, true, 12 * GB, 0);
        Assert.False(v.Valide);
        Assert.Contains("processore", v.Motivo);
    }

    [Fact]
    public void IlMotoreNonContaNelProcessore()
    {
        var (c, ms) = Minuto(0.95, motore: 0.8);
        Assert.True(c.Valuta(ms, true, true, 12 * GB, 0).Valide);
    }

    [Fact]
    public void ServeUnMinutoDiMisure()
    {
        var (c, ms) = Minuto(0.1, secondi: 30);
        var v = c.Valuta(ms, true, true, 12 * GB, 0);
        Assert.False(v.Valide);
        Assert.Contains("minuto", v.Motivo);
    }

    [Fact]
    public void ContaSoloLUltimoMinuto()
    {
        var c = new CondizioniModello();
        long totale = 5_000_000 * 8;
        long ms = 0;
        for (int s = 5; s <= 60; s += 5) c.AggiungiCpu(ms = s * 1000L, totale, 0, 0);         // un minuto al 100%
        for (int s = 65; s <= 125; s += 5) c.AggiungiCpu(ms = s * 1000L, totale, totale, 0);  // poi un minuto fermo
        Assert.True(c.Valuta(ms, true, true, 12 * GB, 0).Valide);
    }
}

public class DomandeModelloTest
{
    [Fact]
    public void LavoroValido() => Assert.Null(DomandeModello.ProblemaLavoro(Dati.LavoroFinto()));

    [Fact]
    public void LavoriNonValidi()
    {
        var l = Dati.LavoroFinto();
        l.Domande.Clear();
        Assert.NotNull(DomandeModello.ProblemaLavoro(l));

        l = Dati.LavoroFinto();
        l.ImmagineJpegBase64 = Convert.ToBase64String(new byte[] { 0x89, 0x50, 0x4E, 0x47 });
        Assert.Contains("JPEG", DomandeModello.ProblemaLavoro(l));

        l = Dati.LavoroFinto();
        l.ImmagineJpegBase64 = "%%%";
        Assert.NotNull(DomandeModello.ProblemaLavoro(l));

        l = Dati.LavoroFinto();
        l.Domande[1].Id = "in_mano";
        Assert.NotNull(DomandeModello.ProblemaLavoro(l));

        l = Dati.LavoroFinto();
        l.Domande[0].Opzioni.Clear();
        Assert.NotNull(DomandeModello.ProblemaLavoro(l));
    }

    [Fact]
    public void AccettaAncheUnDataUrl()
    {
        var l = Dati.LavoroFinto();
        l.ImmagineJpegBase64 = "data:image/jpeg;base64," + l.ImmagineJpegBase64;
        Assert.Null(DomandeModello.ProblemaLavoro(l));
    }

    [Fact]
    public void LaRichiestaVincolaLeRispostePerOgniDomanda()
    {
        var l = Dati.LavoroFinto();
        var corpo = JsonNode.Parse(DomandeModello.CorpoRichiesta(l, "Qwen3.5-9B-Q4_K_M"))!;
        Assert.Equal("Qwen3.5-9B-Q4_K_M", corpo["model"]!.GetValue<string>());
        Assert.Equal(0, corpo["temperature"]!.GetValue<int>());
        var schema = corpo["response_format"]!["json_schema"]!["schema"]!;
        Assert.Equal("json_schema", corpo["response_format"]!["type"]!.GetValue<string>());
        var enumInMano = schema["properties"]!["in_mano"]!["enum"]!.AsArray().Select(n => n!.GetValue<string>()).ToList();
        Assert.Equal(l.Domande[0].Opzioni, enumInMano);
        Assert.Equal(2, schema["required"]!.AsArray().Count);
        Assert.False(schema["additionalProperties"]!.GetValue<bool>());
        var contenuto = corpo["messages"]![1]!["content"]!.AsArray();
        Assert.StartsWith("data:image/jpeg;base64,/9j/", contenuto[0]!["image_url"]!["url"]!.GetValue<string>());
        var testo = contenuto[1]!["text"]!.GetValue<string>();
        Assert.Contains("Camera, sul divano", testo);
        Assert.Contains("in_mano: Cosa tiene in mano la persona?", testo);
        Assert.Contains("telefono, tablet, libro", testo);
        Assert.False(corpo["chat_template_kwargs"]!["enable_thinking"]!.GetValue<bool>());
    }

    [Fact]
    public void RispostaGiusta()
    {
        var e = DomandeModello.LeggiRisposta(Dati.RispostaChat("{\"in_mano\": \"telefono\", \"schermo_acceso\": \"si\"}"), Dati.LavoroFinto());
        Assert.True(e.Ok);
        Assert.Equal("telefono", e.Risposte!["in_mano"]);
        Assert.Equal("si", e.Risposte["schermo_acceso"]);
        Assert.Empty(e.Sostituite);
    }

    [Fact]
    public void RispostaConPensieroEBlocchiDiCodice()
    {
        var e = DomandeModello.LeggiRisposta(
            Dati.RispostaChat("<think>vedo un libro</think>\n```json\n{\"in_mano\": \"Libro\", \"schermo_acceso\": \"no\"}\n```"),
            Dati.LavoroFinto());
        Assert.True(e.Ok);
        Assert.Equal("libro", e.Risposte!["in_mano"]);
    }

    [Fact]
    public void FuoriElenco_DiventaNonSiCapisce()
    {
        var e = DomandeModello.LeggiRisposta(Dati.RispostaChat("{\"in_mano\": \"smartphone\"}"), Dati.LavoroFinto());
        Assert.True(e.Ok);
        Assert.Equal("non_si_capisce", e.Risposte!["in_mano"]);
        Assert.Equal("non_si_capisce", e.Risposte["schermo_acceso"]);
        Assert.Equal(new[] { "in_mano", "schermo_acceso" }, e.Sostituite);
    }

    [Fact]
    public void FuoriElencoSenzaDubbio_NonSiRisponde()
    {
        var l = Dati.LavoroFinto();
        l.Domande[1].Opzioni = new List<string> { "si", "no" };
        var e = DomandeModello.LeggiRisposta(Dati.RispostaChat("{\"in_mano\": \"libro\", \"schermo_acceso\": \"forse\"}"), l);
        Assert.False(e.Ok);
        Assert.Contains("schermo_acceso", e.Errore);
    }

    [Theory]
    [InlineData("non è json")]
    [InlineData("{\"choices\": []}")]
    [InlineData("{\"choices\": [{\"message\": {\"content\": \"\"}}]}")]
    public void RisposteRotte(string corpo) => Assert.False(DomandeModello.LeggiRisposta(corpo, Dati.LavoroFinto()).Ok);

    [Fact]
    public void ContenutoSenzaJson() =>
        Assert.False(DomandeModello.LeggiRisposta(Dati.RispostaChat("Vedo una persona con un libro."), Dati.LavoroFinto()).Ok);
}

public class TrovaMotoreTest
{
    private static readonly string[] Cartelle =
    {
        @"C:\u\.lmstudio\extensions\backends\llama.cpp-win-x86_64-avx2-2.28.2",
        @"C:\u\.lmstudio\extensions\backends\llama.cpp-win-x86_64-avx2-2.43.0",
        @"C:\u\.lmstudio\extensions\backends\llama.cpp-win-x86_64-avx2-2.9.9",
        @"C:\u\.lmstudio\extensions\backends\llama.cpp-win-x86_64-vulkan-avx2-2.50.0",
        @"C:\u\.lmstudio\extensions\backends\llama.cpp-win-x86_64-nvidia-cuda-avx2-2.60.0",
        @"C:\u\.lmstudio\extensions\backends\llama.cpp-win-x86_64-avx2-nuovo",
        @"C:\u\.lmstudio\extensions\backends\vendor",
    };

    [Fact]
    public void PrendeLaVersionePiuAlta() =>
        Assert.EndsWith("avx2-2.43.0", TrovaMotore.CartellaPiùRecente(Cartelle, "llama.cpp-win-x86_64-avx2-"));

    [Fact]
    public void NienteCartelle() => Assert.Null(TrovaMotore.CartellaPiùRecente(new[] { "vendor" }, "llama.cpp-win-x86_64-avx2-"));

    [Fact]
    public void PercorsoDallaCartellaPiuRecente()
    {
        var cfg = new ConfigMotore { CartellaBackends = @"C:\u\.lmstudio\extensions\backends" };
        var exe = TrovaMotore.LlamaServer(cfg, _ => Cartelle, _ => true, out var motivo);
        Assert.Equal(@"C:\u\.lmstudio\extensions\backends\llama.cpp-win-x86_64-avx2-2.43.0\llama-server.exe", exe);
        Assert.Equal("ok", motivo);
    }

    [Fact]
    public void PercorsoEsplicitoVince()
    {
        var cfg = new ConfigMotore { LlamaServer = @"D:\motori\llama-server.exe" };
        Assert.Equal(@"D:\motori\llama-server.exe", TrovaMotore.LlamaServer(cfg, _ => Cartelle, _ => true, out _));
        Assert.Null(TrovaMotore.LlamaServer(cfg, _ => Cartelle, _ => false, out var motivo));
        Assert.Contains("non trovo", motivo);
    }

    [Fact]
    public void ExeMancante()
    {
        var cfg = new ConfigMotore { CartellaBackends = "x" };
        Assert.Null(TrovaMotore.LlamaServer(cfg, _ => Cartelle, _ => false, out var motivo));
        Assert.Contains("llama-server.exe", motivo);
        Assert.Null(TrovaMotore.LlamaServer(cfg, _ => throw new DirectoryNotFoundException(), _ => true, out motivo));
        Assert.Contains("cartella dei motori", motivo);
    }

    [Fact]
    public void ArgomentiSoloProcessoreESoloLocale()
    {
        var a = TrovaMotore.Argomenti(new ConfigMotore { Thread = 6, Porta = 8781 }).ToList();
        Assert.Equal("127.0.0.1", a[a.IndexOf("--host") + 1]);
        Assert.Equal("8781", a[a.IndexOf("--port") + 1]);
        Assert.Equal("0", a[a.IndexOf("-ngl") + 1]);
        Assert.Equal("6", a[a.IndexOf("-t") + 1]);
        Assert.Contains("--offline", a);
        Assert.Contains("--no-webui", a);
        Assert.Contains("--mmproj", a);
    }
}
