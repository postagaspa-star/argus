using System.Diagnostics;
using System.Net;
using System.Text.Json;
using Argus.Nucleo;
using Xunit.Abstractions;

namespace Argus.Prove;

/// <summary>
/// Le prove col motore vero (llama-server di LM Studio + un modello PICCOLO della stessa famiglia). Lente e
/// facoltative: partono solo con ARGUS_PROVA_MOTORE=1. Il modello piccolo sta in
/// %USERPROFILE%\argus-build\modelli-prova (mai dentro OneDrive); l'immagine in %USERPROFILE%\argus-build\prove-immagini.
/// </summary>
public sealed class ProvaMotoreVeroAttribute : FactAttribute
{
    public ProvaMotoreVeroAttribute()
    {
        if (Environment.GetEnvironmentVariable("ARGUS_PROVA_MOTORE") != "1")
            Skip = "Prova del motore vero: serve ARGUS_PROVA_MOTORE=1 e il modello piccolo in argus-build\\modelli-prova.";
    }
}

public class MotoreVeroTest
{
    private readonly ITestOutputHelper uscita;

    public MotoreVeroTest(ITestOutputHelper uscita)
    {
        this.uscita = uscita;
    }

    private static string Build => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "argus-build");

    private static ConfigMotore Config(int porta) => new()
    {
        Modello = Path.Combine(Build, "modelli-prova", "Qwen3.5-0.8B-Q4_K_M.gguf"),
        Mmproj = Path.Combine(Build, "modelli-prova", "mmproj-Qwen3.5-0.8B-BF16.gguf"),
        NomeModello = "Qwen3.5-0.8B-Q4_K_M",
        Porta = porta,
        SecondiCaricamento = 180,
        SecondiRisposta = 170,
    };

    private static Lavoro LavoroVero(string id)
    {
        var img = File.ReadAllBytes(Path.Combine(Build, "prove-immagini", "paesaggio.jpg"));
        return new Lavoro
        {
            Id = id,
            ImmagineJpegBase64 = Convert.ToBase64String(img),
            Contesto = "Prova del motore: una foto qualsiasi.",
            Domande =
            {
                new DomandaLavoro { Id = "persona", Domanda = "Nella foto c'è una persona?", Opzioni = { "si", "no", "non_si_capisce" } },
                new DomandaLavoro { Id = "cosa", Domanda = "Che cosa si vede soprattutto?", Opzioni = { "paesaggio", "stanza", "persona", "schermo", "non_si_capisce" } },
                new DomandaLavoro { Id = "in_mano", Domanda = "Cosa tiene in mano la persona?", Opzioni = { "telefono", "tablet", "libro", "quaderno", "controller", "niente", "non_si_capisce" } },
            },
            Scade = "2099-01-01T00:00:00+01:00",
        };
    }

    private void Scrivi(string riga)
    {
        uscita.WriteLine(riga);
        try
        {
            File.AppendAllText(Path.Combine(Build, "prova-motore.txt"), $"{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss} {riga}{Environment.NewLine}");
        }
        catch (IOException)
        {
        }
    }

    [ProvaMotoreVero]
    public async Task CatenaImmagineRisposta_EMaiDueCopie()
    {
        var cfg = Config(8791);
        Log.Imposta(Path.Combine(Build, "log-prove"), "motore.log");
        using var motore = new MotoreLlama(cfg, Path.Combine(Build, "log-prove", "llama-server.log"), Firma.Soggetto);
        var t = Stopwatch.StartNew();
        var errore = await motore.AvviaAsync(CancellationToken.None);
        Assert.Null(errore);
        Scrivi($"motore pronto in {t.ElapsedMilliseconds} ms (modello 0.8B, {cfg.ThreadEffettivi()} thread)");

        // Mai due copie: un secondo motore sulla stessa porta non parte.
        using (var secondo = new MotoreLlama(cfg, null, Firma.Soggetto))
        {
            var e2 = await secondo.AvviaAsync(CancellationToken.None);
            Assert.NotNull(e2);
            Assert.Contains("porta", e2);
        }

        for (int i = 1; i <= 2; i++)
        {
            var lavoro = LavoroVero("vero-" + i);
            t.Restart();
            var r = await motore.ChiediAsync(DomandeModello.CorpoRichiesta(lavoro, cfg.NomeModello), TimeSpan.FromSeconds(170), CancellationToken.None);
            long ms = t.ElapsedMilliseconds;
            Assert.True(r.Ok, r.Errore + " " + r.Corpo);
            var esito = DomandeModello.LeggiRisposta(r.Corpo!, lavoro);
            Assert.True(esito.Ok, esito.Errore);
            foreach (var d in lavoro.Domande) Assert.Contains(esito.Risposte![d.Id], d.Opzioni);
            Scrivi($"domanda {i}: {ms} ms, risposte {JsonSerializer.Serialize(esito.Risposte)}, sostituite {esito.Sostituite.Count}, memoria motore {motore.Memoria() / (1024 * 1024)} MB");
        }

        motore.Spegni("fine prova");
        Assert.False(motore.Acceso);
        Assert.False(await MotoreLlama.PortaOccupataAsync(cfg.Porta));
    }

    [ProvaMotoreVero]
    public async Task DalNasFintoAlMotoreVero()
    {
        var cfg = Config(8792);
        var lavoro = LavoroVero("nas-1");
        var nas = new NasFinto();
        bool dato = false;
        nas.Risposta = q =>
        {
            if (q.Metodo == HttpMethod.Get && !dato)
            {
                dato = true;
                return NasFinto.Json(JsonSerializer.Serialize(lavoro, JsonArgus.Opzioni));
            }
            if (q.Metodo == HttpMethod.Get) return new HttpResponseMessage(HttpStatusCode.NoContent);
            return NasFinto.Json("{\"ok\": true}");
        };
        using var client = new ClientNas("http://nas.finto:8700", "t", nas);
        using var motore = new MotoreLlama(cfg, null, Firma.Soggetto);
        var orologio = new OrologioFinto(DateTimeOffset.Now);
        var gestore = new GestoreLavori(cfg, client, motore, new MisureFinte(), orologio);
        var t = Stopwatch.StartNew();
        for (int i = 0; i < 14 && gestore.LavoriFatti == 0; i++)
        {
            orologio.Avanza(GestoreLavori.Passo);
            await gestore.PassoAsync(CancellationToken.None);
        }
        Assert.Equal(1, gestore.LavoriFatti);
        var invio = nas.Richieste.Single(r => r.Metodo == HttpMethod.Post);
        Assert.Equal("/api/pc/lavori/nas-1", invio.Percorso);
        var corpo = JsonDocument.Parse(invio.Corpo!).RootElement;
        Scrivi($"dal NAS finto al motore vero e ritorno: {t.ElapsedMilliseconds} ms in tutto (accensione compresa), " +
               $"millisecondi del modello {corpo.GetProperty("millisecondi").GetInt64()}, risposte {corpo.GetProperty("risposte").GetRawText()}");
        motore.Spegni("fine prova");
    }
}
