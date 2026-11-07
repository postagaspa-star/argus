using System.Net;
using System.Text.Json;
using Argus.Nucleo;

namespace Argus.Prove;

/// <summary>Un motore finto: si accende subito e risponde quello che gli si dice.</summary>
public sealed class MotoreFinto : IMotore
{
    public bool Acceso { get; private set; }
    public int Accensioni { get; private set; }
    public List<string> Spegnimenti { get; } = new();
    public List<string> Domande { get; } = new();
    public string? ErroreAvvio { get; set; }
    public string Contenuto { get; set; } = "{\"in_mano\": \"libro\", \"schermo_acceso\": \"no\"}";
    public TimeSpan Ritardo { get; set; } = TimeSpan.Zero;
    public long Cpu { get; set; }

    public Task<string?> AvviaAsync(CancellationToken ct)
    {
        Accensioni++;
        if (ErroreAvvio != null) return Task.FromResult<string?>(ErroreAvvio);
        Acceso = true;
        return Task.FromResult<string?>(null);
    }

    public async Task<RispostaMotore> ChiediAsync(string corpoJson, TimeSpan tempo, CancellationToken ct)
    {
        Domande.Add(corpoJson);
        try
        {
            if (Ritardo > TimeSpan.Zero) await Task.Delay(Ritardo, ct);
        }
        catch (OperationCanceledException)
        {
            return new RispostaMotore(false, null, "domanda annullata", true);
        }
        return new RispostaMotore(true, Dati.RispostaChat(Contenuto), null);
    }

    public void Spegni(string motivo)
    {
        if (!Acceso) return;
        Acceso = false;
        Spegnimenti.Add(motivo);
    }

    public long Memoria() => Acceso ? 6L * 1024 * 1024 * 1024 : 0;
    public long TempoCpu() => Cpu;
    public void Dispose() { }
}

/// <summary>Misure finte: ogni lettura fa avanzare i contatori di 5 secondi su 8 processori.</summary>
public sealed class MisureFinte : IMisure
{
    private long totale, inattivo;
    public double Occupato { get; set; } = 0.1;
    public bool? Corrente { get; set; } = true;
    public long Libera { get; set; } = 12L * 1024 * 1024 * 1024;

    public MisuraPc Leggi()
    {
        long passo = 5_000_000L * 8;
        totale += passo;
        inattivo += (long)(passo * (1 - Occupato));
        return new MisuraPc(totale, inattivo, Corrente, true, Libera);
    }
}

public class GestoreLavoriTest
{
    private sealed class Banco
    {
        public readonly OrologioFinto Orologio = new(Dati.Lunedi(15));
        public readonly NasFinto Nas = new();
        public readonly MotoreFinto Motore = new();
        public readonly MisureFinte Misure = new();
        public readonly GestoreLavori Gestore;
        public readonly ClientNas Client;
        public int Lavori;
        public Queue<Lavoro> Coda { get; } = new();

        public Banco(ConfigMotore? cfg = null)
        {
            Nas.Risposta = q =>
            {
                if (q.Metodo == HttpMethod.Get && q.Percorso == "/api/pc/lavori")
                {
                    Lavori++;
                    return Coda.Count == 0
                        ? new HttpResponseMessage(HttpStatusCode.NoContent)
                        : NasFinto.Json(JsonSerializer.Serialize(Coda.Dequeue(), JsonArgus.Opzioni));
                }
                return NasFinto.Json("{\"ok\": true}");
            };
            Client = new ClientNas("http://nas.finto:8700", "t", Nas);
            Gestore = new GestoreLavori(cfg ?? new ConfigMotore(), Client, Motore, Misure, Orologio);
        }

        /// <summary>Fa passare il tempo a passi di 5 secondi.</summary>
        public async Task Passa(TimeSpan quanto)
        {
            for (var t = TimeSpan.Zero; t < quanto; t += GestoreLavori.Passo)
            {
                Orologio.Avanza(GestoreLavori.Passo);
                await Gestore.PassoAsync(CancellationToken.None);
            }
        }

        public List<NasFinto.Richiesta> Risposte => Nas.Richieste.Where(r => r.Metodo == HttpMethod.Post).ToList();
    }

    [Fact]
    public async Task PrimaDiUnMinutoNonChiedeLavori()
    {
        var b = new Banco();
        await b.Passa(TimeSpan.FromSeconds(45));
        Assert.Equal(0, b.Lavori);
        Assert.False(b.Gestore.UltimaVerifica.Valide);
    }

    [Fact]
    public async Task ConLeCondizioniChiedeOgni15Secondi()
    {
        var b = new Banco();
        await b.Passa(TimeSpan.FromSeconds(60));
        int primo = b.Lavori;
        Assert.True(primo >= 1);
        await b.Passa(TimeSpan.FromSeconds(60));
        Assert.Equal(primo + 4, b.Lavori);
        Assert.False(b.Motore.Acceso); // senza lavori il motore resta spento
    }

    [Fact]
    public async Task UnLavoroAccendeIlMotoreERisponde()
    {
        var b = new Banco();
        b.Coda.Enqueue(Dati.LavoroFinto("l-7"));
        await b.Passa(TimeSpan.FromSeconds(70));
        Assert.True(b.Motore.Acceso);
        Assert.Equal(1, b.Motore.Accensioni);
        Assert.Single(b.Motore.Domande);
        var invio = Assert.Single(b.Risposte);
        Assert.Equal("/api/pc/lavori/l-7", invio.Percorso);
        var corpo = JsonDocument.Parse(invio.Corpo!).RootElement;
        Assert.Equal("libro", corpo.GetProperty("risposte").GetProperty("in_mano").GetString());
        Assert.Equal("no", corpo.GetProperty("risposte").GetProperty("schermo_acceso").GetString());
        Assert.Equal("Qwen3.5-9B-Q4_K_M", corpo.GetProperty("modello").GetString());
        Assert.Equal(1, b.Gestore.LavoriFatti);
    }

    [Fact]
    public async Task CinqueMinutiSenzaLavoriSpegne()
    {
        var b = new Banco();
        b.Coda.Enqueue(Dati.LavoroFinto());
        await b.Passa(TimeSpan.FromSeconds(70));
        Assert.True(b.Motore.Acceso);
        await b.Passa(TimeSpan.FromMinutes(4));
        Assert.True(b.Motore.Acceso);
        await b.Passa(TimeSpan.FromMinutes(1.1));
        Assert.False(b.Motore.Acceso);
        Assert.Contains("5 minuti senza lavori", b.Motore.Spegnimenti.Single());
    }

    [Fact]
    public async Task DueLavoriUnSoloMotore()
    {
        var b = new Banco();
        b.Coda.Enqueue(Dati.LavoroFinto("a"));
        b.Coda.Enqueue(Dati.LavoroFinto("b"));
        await b.Passa(TimeSpan.FromSeconds(100));
        Assert.Equal(1, b.Motore.Accensioni);
        Assert.Equal(2, b.Risposte.Count);
    }

    [Fact]
    public async Task ABatteriaSpegneSubito()
    {
        var b = new Banco();
        b.Coda.Enqueue(Dati.LavoroFinto());
        await b.Passa(TimeSpan.FromSeconds(70));
        Assert.True(b.Motore.Acceso);
        b.Misure.Corrente = false;
        await b.Passa(TimeSpan.FromSeconds(5));
        Assert.False(b.Motore.Acceso);
        Assert.Contains("batteria", b.Motore.Spegnimenti.Single());
        int lavori = b.Lavori;
        await b.Passa(TimeSpan.FromSeconds(60));
        Assert.Equal(lavori, b.Lavori); // a batteria non si chiede niente
    }

    [Fact]
    public async Task ProcessoreOccupatoNonChiede()
    {
        var b = new Banco();
        b.Misure.Occupato = 0.7;
        await b.Passa(TimeSpan.FromSeconds(120));
        Assert.Equal(0, b.Lavori);
        Assert.Contains("processore", b.Gestore.UltimaVerifica.Motivo);
    }

    [Fact]
    public async Task IlMotoreCheLavoraNonSiSpegneDaSolo()
    {
        var b = new Banco();
        b.Coda.Enqueue(Dati.LavoroFinto());
        await b.Passa(TimeSpan.FromSeconds(70));
        // Il motore usa quasi tutto il processore: non conta.
        b.Misure.Occupato = 0.9;
        b.Motore.Cpu += 0; // il contatore del motore cresce sotto
        for (int i = 0; i < 12; i++)
        {
            b.Motore.Cpu += (long)(5_000_000L * 8 * 0.85);
            await b.Passa(TimeSpan.FromSeconds(5));
        }
        Assert.True(b.Motore.Acceso);
        Assert.True(b.Gestore.UltimaVerifica.Valide, b.Gestore.UltimaVerifica.Motivo);
    }

    [Fact]
    public async Task RispostaFuoriElencoSenzaDubbio_NonSiManda()
    {
        var b = new Banco();
        var l = Dati.LavoroFinto();
        l.Domande[1].Opzioni = new List<string> { "si", "no" };
        b.Coda.Enqueue(l);
        b.Motore.Contenuto = "{\"in_mano\": \"libro\", \"schermo_acceso\": \"forse\"}";
        await b.Passa(TimeSpan.FromSeconds(70));
        Assert.Empty(b.Risposte);
        Assert.Contains("fuori elenco", b.Gestore.UltimoErrore);
    }

    [Fact]
    public async Task LavoroScadutoONonValido_SiSalta()
    {
        var b = new Banco();
        var scaduto = Dati.LavoroFinto("vecchio");
        scaduto.Scade = "2026-11-08T23:59:59+01:00";
        var rotto = Dati.LavoroFinto("rotto");
        rotto.Domande.Clear();
        b.Coda.Enqueue(scaduto);
        b.Coda.Enqueue(rotto);
        await b.Passa(TimeSpan.FromSeconds(90));
        Assert.Equal(0, b.Motore.Accensioni);
        Assert.Empty(b.Risposte);
    }

    [Fact]
    public async Task MotoreCheNonParte_PausaDiDieciMinuti()
    {
        var b = new Banco();
        b.Motore.ErroreAvvio = "manca il modello";
        b.Coda.Enqueue(Dati.LavoroFinto("a"));
        b.Coda.Enqueue(Dati.LavoroFinto("b"));
        await b.Passa(TimeSpan.FromSeconds(70));
        Assert.Equal(1, b.Motore.Accensioni);
        int lavori = b.Lavori;
        await b.Passa(TimeSpan.FromMinutes(9));
        Assert.Equal(lavori, b.Lavori);
        await b.Passa(TimeSpan.FromMinutes(1.5));
        Assert.True(b.Lavori > lavori);
        Assert.Equal("manca il modello", b.Gestore.UltimoErrore);
    }

    [Fact]
    public async Task Spento_NienteLavori()
    {
        var b = new Banco(new ConfigMotore { Attivo = false });
        b.Coda.Enqueue(Dati.LavoroFinto());
        await b.Passa(TimeSpan.FromSeconds(120));
        Assert.Equal(0, b.Lavori);
    }
}
