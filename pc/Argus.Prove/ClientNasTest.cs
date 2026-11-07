using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using Argus.Nucleo;

namespace Argus.Prove;

public class ClientNasTest
{
    private const string StatoEsempio = """
    {
      "ora_server": "2026-11-09T15:20:00+01:00",
      "modalita": "studio",
      "liste_versione": 7,
      "quota": {"fatti": 25, "totale": 60, "sospeso": 4, "aggiunte": 6, "pausa_disponibile": 10, "fine_prevista": "16:05"},
      "classe_adesso": "studio",
      "comando_attivo": {"tipo": "lv", "fino": "16:25"},
      "verdetti": {"bbfbe152f12cc352f1409729a818d464dc16a911": "studio"},
      "messaggio_copertura": "Adesso è tempo di studio. Mancano 35 minuti.",
      "sblocco_fino": null,
      "quota_fatta_oggi": false,
      "di_voce": {"id": "v1", "url": "/api/pc/voce/v1.wav"}
    }
    """;

    [Fact]
    public async Task StatoConTokenBearer()
    {
        var nas = new NasFinto { Risposta = _ => NasFinto.Json(StatoEsempio) };
        using var c = new ClientNas("http://nas.finto:8700", "segreto", nas);
        var r = await c.StatoAsync();
        Assert.True(r.Ok);
        Assert.Equal("Bearer segreto", nas.Richieste[0].Autorizzazione);
        Assert.Equal("/api/pc/stato", nas.Richieste[0].Percorso);
        var s = r.Dati!;
        Assert.Equal("studio", s.Modalita);
        Assert.Equal(7, s.ListeVersione);
        Assert.Equal(25, s.Quota!.Fatti);
        Assert.Equal("16:05", s.Quota.FinePrevista);
        Assert.Equal("lv", s.ComandoAttivo!.Tipo);
        Assert.Equal("studio", s.Verdetti!["bbfbe152f12cc352f1409729a818d464dc16a911"]);
        Assert.Equal("/api/pc/voce/v1.wav", s.DiVoce!.Url);
        Assert.False(s.QuotaFattaOggi);
    }

    [Fact]
    public async Task SaluteSenzaToken()
    {
        var nas = new NasFinto { Risposta = _ => NasFinto.Json("{\"ok\": true, \"versione\": \"1.0.0\", \"telecamere\": {\"camera\": \"ok\"}, \"decisore\": \"ok\", \"voci\": \"assente\"}") };
        using var c = new ClientNas("http://nas.finto:8700/", "segreto", nas);
        var r = await c.SaluteAsync();
        Assert.True(r.Ok);
        Assert.Null(nas.Richieste[0].Autorizzazione);
        Assert.Equal("1.0.0", r.Dati!.Versione);
    }

    [Fact]
    public async Task TokenSbagliato_ErroreInItaliano()
    {
        var nas = new NasFinto { Risposta = _ => NasFinto.Json("{\"errore\": \"Token sbagliato.\", \"codice\": \"token\"}", HttpStatusCode.Unauthorized) };
        using var c = new ClientNas("http://nas.finto:8700", "sbagliato", nas);
        var r = await c.StatoAsync();
        Assert.False(r.Ok);
        Assert.True(r.Raggiunto);
        Assert.Equal(401, r.Stato);
        Assert.Equal("Token sbagliato.", r.Errore);
        Assert.Equal("token", r.Codice);
        Assert.DoesNotContain("sbagliato", r.Errore!.Replace("Token sbagliato.", ""));
    }

    [Fact]
    public async Task ErroreSenzaCorpo()
    {
        var nas = new NasFinto { Risposta = _ => new HttpResponseMessage(HttpStatusCode.InternalServerError) };
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        var r = await c.StatoAsync();
        Assert.False(r.Ok);
        Assert.Equal("Il NAS ha risposto con un errore (500).", r.Errore);
    }

    [Fact]
    public async Task JsonRotto()
    {
        var nas = new NasFinto { Risposta = _ => NasFinto.Json("{ non va") };
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        var r = await c.StatoAsync();
        Assert.False(r.Ok);
        Assert.True(r.Raggiunto);
        Assert.Equal("json", r.Codice);
        Assert.Contains("non capisco", r.Errore);
    }

    [Fact]
    public async Task NasCheNonRisponde_TempoBreve()
    {
        using var c = new ClientNas("http://nas.finto:8700", "t", new NasMuto()) { TempoBreve = TimeSpan.FromMilliseconds(200) };
        var cronometro = System.Diagnostics.Stopwatch.StartNew();
        var r = await c.StatoAsync();
        Assert.False(r.Ok);
        Assert.False(r.Raggiunto);
        Assert.Equal("Il NAS non risponde.", r.Errore);
        Assert.Equal("timeout", r.Codice);
        Assert.True(cronometro.ElapsedMilliseconds < 3000);
    }

    [Fact]
    public async Task ListeNormalizzate()
    {
        var nas = new NasFinto { Risposta = _ => NasFinto.Json("{\"versione\": 9, \"studio\": {\"programmi\": [\"SOFFICE.EXE\"], \"siti\": [\"https://Treccani.it/\"]}, \"browser\": [\"Chrome.exe\"]}") };
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        var r = await c.ListeAsync();
        Assert.True(r.Ok);
        Assert.Equal(9, r.Dati!.Versione);
        Assert.Contains("soffice.exe", r.Dati.Studio.Programmi);
        Assert.Contains("treccani.it", r.Dati.Studio.Siti);
        Assert.True(r.Dati.ÈBrowser("chrome.exe"));
    }

    [Fact]
    public async Task AttivitaConINomiDelContratto()
    {
        var nas = new NasFinto();
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        var campione = new Campione
        {
            Ts = "2026-11-09T15:20:00.000+01:00", Processo = "chrome.exe", Titolo = "Rivoluzione francese - Wikipedia",
            Dominio = "it.wikipedia.org", Permesso = true, Coperto = false, InattivoSecondi = 3, Audio = { "lectio.exe" },
            SchermoBloccato = false, PactumCopre = false,
        };
        var r = await c.AttivitaAsync(new[] { campione });
        Assert.True(r.Ok);
        var corpo = JsonDocument.Parse(nas.Richieste[0].Corpo!).RootElement;
        var p = corpo.GetProperty("campioni")[0];
        Assert.Equal("chrome.exe", p.GetProperty("processo").GetString());
        Assert.Equal("it.wikipedia.org", p.GetProperty("dominio").GetString());
        Assert.Equal(3, p.GetProperty("inattivo_secondi").GetInt32());
        Assert.Equal("lectio.exe", p.GetProperty("audio")[0].GetString());
        Assert.False(p.GetProperty("schermo_bloccato").GetBoolean());
        Assert.False(p.GetProperty("pactum_copre").GetBoolean());
        Assert.True(p.GetProperty("permesso").GetBoolean());
        Assert.False(p.GetProperty("coperto").GetBoolean());
        Assert.Equal("/api/pc/attivita", nas.Richieste[0].Percorso);
    }

    [Fact]
    public async Task TitoloNullSiMandaComeNull()
    {
        var nas = new NasFinto();
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        await c.AttivitaAsync(new[] { new Campione { Ts = "x", Processo = "spotify.exe" } });
        var p = JsonDocument.Parse(nas.Richieste[0].Corpo!).RootElement.GetProperty("campioni")[0];
        Assert.Equal(JsonValueKind.Null, p.GetProperty("titolo").ValueKind);
    }

    [Fact]
    public async Task ComandoCapitoEChiedeFoto()
    {
        var nas = new NasFinto
        {
            Risposta = _ => NasFinto.Json("{\"ok\": true, \"risposta\": \"Scatta 6 foto.\", \"chiede_foto\": {\"tipo\": \"lb\", \"nome\": \"storia\", \"scatti\": 6, \"consiglio\": \"Copertina e 2-3 pagine aperte.\"}}"),
        };
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        var r = await c.ComandoAsync("lb storia");
        Assert.True(r.Ok);
        Assert.Equal("lb", r.Dati!.ChiedeFoto!.Tipo);
        Assert.Equal(6, r.Dati.ChiedeFoto.Scatti);
        Assert.Equal("{\"testo\":\"lb storia\"}", nas.Richieste[0].Corpo);
    }

    [Fact]
    public async Task ComandoNonCapito_TieneLaRisposta()
    {
        var nas = new NasFinto { Risposta = _ => NasFinto.Json("{\"ok\": false, \"risposta\": \"Non ho capito. Scrivi così: ps m: bagno & t: 10\", \"chiede_foto\": null}") };
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        var r = await c.ComandoAsync("ps boh");
        Assert.True(r.Ok); // HTTP 200
        Assert.False(r.Dati!.Ok);
        Assert.StartsWith("Non ho capito.", r.Dati.Risposta);

        nas.Risposta = _ => NasFinto.Json("{\"ok\": false, \"risposta\": \"Non ho capito.\"}", HttpStatusCode.UnprocessableEntity);
        var r2 = await c.ComandoAsync("ps boh");
        Assert.False(r2.Ok);
        Assert.Equal("Non ho capito.", r2.Dati?.Risposta);
    }

    [Fact]
    public async Task FotoMultipart()
    {
        var nas = new NasFinto { Risposta = _ => NasFinto.Json("{\"ok\": true, \"risposta\": \"«storia» salvato (2 foto).\"}") };
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        var r = await c.FotoAsync("lb", "storia", new[] { new ImmagineFoto(Dati.JpegMinimo, "image/jpeg"), new ImmagineFoto(Dati.JpegMinimo, "image/jpeg") });
        Assert.True(r.Ok);
        Assert.Equal("«storia» salvato (2 foto).", r.Dati!.Risposta);
        var q = nas.Richieste[0];
        Assert.Equal("multipart/form-data", q.TipoContenuto);
        Assert.Contains("form-data; name=\"tipo\"", q.Corpo);
        Assert.Contains("form-data; name=\"nome\"", q.Corpo);
        Assert.Contains("name=\"immagini\"; filename=\"foto-1.jpg\"", q.Corpo);
        Assert.Contains("name=\"immagini\"; filename=\"foto-2.jpg\"", q.Corpo);
        Assert.Contains("Content-Type: image/jpeg", q.Corpo);
    }

    [Fact]
    public async Task FotoTroppeOGrandi()
    {
        using var c = new ClientNas("http://nas.finto:8700", "t", new NasFinto());
        Assert.False((await c.FotoAsync("vs", null, Array.Empty<ImmagineFoto>())).Ok);
        var grande = new ImmagineFoto(new byte[9 * 1024 * 1024], "image/jpeg");
        Assert.Contains("8 MB", (await c.FotoAsync("vs", null, new[] { grande })).Errore);
    }

    [Fact]
    public async Task LavoriConNiente204()
    {
        var nas = new NasFinto { Risposta = _ => new HttpResponseMessage(HttpStatusCode.NoContent) };
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        var r = await c.LavoroAsync();
        Assert.True(r.Ok);
        Assert.Null(r.Dati);
    }

    [Fact]
    public async Task LavoroERisposta()
    {
        var lavoro = JsonSerializer.Serialize(Dati.LavoroFinto(), JsonArgus.Opzioni);
        var nas = new NasFinto { Risposta = q => q.Metodo == HttpMethod.Get ? NasFinto.Json(lavoro) : NasFinto.Json("{\"ok\": true}") };
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        var r = await c.LavoroAsync();
        Assert.Equal("l-1", r.Dati!.Id);
        Assert.Contains("\"immagine_jpeg_base64\"", lavoro);
        Assert.Equal(2, r.Dati.Domande.Count);
        var invio = await c.RispondiLavoroAsync("l-1", new RispostaLavoro { Risposte = { ["in_mano"] = "libro" }, Millisecondi = 41200, Modello = "Qwen3.5-9B-Q4_K_M" });
        Assert.True(invio.Ok);
        Assert.Equal("/api/pc/lavori/l-1", nas.Richieste[1].Percorso);
        var corpo = JsonDocument.Parse(nas.Richieste[1].Corpo!).RootElement;
        Assert.Equal("libro", corpo.GetProperty("risposte").GetProperty("in_mano").GetString());
        Assert.Equal(41200, corpo.GetProperty("millisecondi").GetInt64());
        Assert.Equal("Qwen3.5-9B-Q4_K_M", corpo.GetProperty("modello").GetString());
    }

    [Fact]
    public async Task OpzioneFuoriElenco_422()
    {
        var nas = new NasFinto { Risposta = _ => NasFinto.Json("{\"errore\": \"Opzione non valida.\", \"codice\": \"opzione\"}", HttpStatusCode.UnprocessableEntity) };
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        var r = await c.RispondiLavoroAsync("l-1", new RispostaLavoro());
        Assert.False(r.Ok);
        Assert.Equal(422, r.Stato);
        Assert.Equal("Opzione non valida.", r.Errore);
    }

    [Fact]
    public async Task Evento()
    {
        var nas = new NasFinto();
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        await c.EventoAsync(TipiEvento.SbloccoEmergenza, Sblocco.Nuovo(4, Dati.Lunedi(15)).DettagliEvento(), Dati.Lunedi(15),
            segretoSblocco: "segreto-sblocco");
        var corpo = JsonDocument.Parse(nas.Richieste[0].Corpo!).RootElement;
        Assert.Equal("sblocco_emergenza", corpo.GetProperty("tipo").GetString());
        Assert.Equal(4, corpo.GetProperty("dettagli").GetProperty("ore").GetInt32());
        Assert.False(corpo.GetProperty("dettagli").TryGetProperty("fino", out _)); // la fine la calcola il NAS
        Assert.Equal("2026-11-09T15:00:00.000+01:00", corpo.GetProperty("ts").GetString());
        Assert.Equal("segreto-sblocco", nas.Richieste[0].SegretoSblocco);
        Assert.Equal("Bearer t", nas.Richieste[0].Autorizzazione);

        // Gli altri eventi senza il segreto.
        await c.EventoAsync(TipiEvento.AgenteRiaperto, new() { ["pid"] = 1 }, Dati.Lunedi(15));
        Assert.Null(nas.Richieste[1].SegretoSblocco);
    }

    [Fact]
    public async Task SbloccoRifiutato_403()
    {
        var nas = new NasFinto { Risposta = _ => NasFinto.Json("{\"errore\": \"Sblocco non autorizzato.\", \"codice\": \"sblocco\"}", HttpStatusCode.Forbidden) };
        using var c = new ClientNas("http://nas.finto:8700", "t", nas);
        var r = await c.EventoAsync(TipiEvento.SbloccoEmergenza, new() { ["ore"] = 2 }, Dati.Lunedi(15));
        Assert.False(r.Ok);
        Assert.True(r.Raggiunto);
        Assert.Equal(403, r.Stato);
        Assert.Equal("sblocco", r.Codice);

        var muto = new NasFinto { Risposta = _ => new HttpResponseMessage(HttpStatusCode.Forbidden) };
        using var c2 = new ClientNas("http://nas.finto:8700", "t", muto);
        var r2 = await c2.EventoAsync(TipiEvento.SbloccoEmergenza, new() { ["ore"] = 2 }, Dati.Lunedi(15));
        Assert.Equal("sblocco", r2.Codice);
        Assert.Contains("sblocco", r2.Errore);
    }

    [Fact]
    public async Task VoceSoloDalloStessoNas()
    {
        var nas = new NasFinto { Risposta = _ => new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(new byte[] { 1, 2, 3 }) } };
        using var c = new ClientNas("http://nas.finto:8700", "segreto", nas);
        var r = await c.VoceAsync("/api/pc/voce/v1.wav");
        Assert.True(r.Ok);
        Assert.Equal(3, r.Dati!.Length);
        Assert.Equal("Bearer segreto", nas.Richieste[0].Autorizzazione);
        var altrove = await c.VoceAsync("http://altro.sito/voce.wav");
        Assert.False(altrove.Ok);
        Assert.Single(nas.Richieste); // il token non è uscito
    }

    [Fact]
    public void IndirizzoNonValido() => Assert.Throws<ErroreConfig>(() => new ClientNas("nas senza schema", "t"));

    [Fact]
    public async Task ServerVeroCheNonRisponde()
    {
        // Un server TCP vero che accetta e poi tace.
        var ascolto = new TcpListener(IPAddress.Loopback, 0);
        ascolto.Start();
        int porta = ((IPEndPoint)ascolto.LocalEndpoint).Port;
        var accetta = ascolto.AcceptTcpClientAsync();
        try
        {
            using var c = new ClientNas($"http://127.0.0.1:{porta}", "t") { TempoBreve = TimeSpan.FromMilliseconds(500) };
            var r = await c.StatoAsync();
            Assert.False(r.Raggiunto);
            Assert.Equal("Il NAS non risponde.", r.Errore);
        }
        finally
        {
            ascolto.Stop();
            try { (await accetta).Dispose(); } catch (Exception) { }
        }
    }

    [Fact]
    public async Task PortaChiusa()
    {
        var ascolto = new TcpListener(IPAddress.Loopback, 0);
        ascolto.Start();
        int porta = ((IPEndPoint)ascolto.LocalEndpoint).Port;
        ascolto.Stop();
        using var c = new ClientNas($"http://127.0.0.1:{porta}", "t");
        var r = await c.StatoAsync();
        Assert.False(r.Raggiunto);
        Assert.Equal("Il NAS non risponde.", r.Errore);
    }

    [Fact]
    public async Task ServerHttpVero()
    {
        // Un piccolo server HTTP vero (socket): risponde allo stato come il NAS.
        var ascolto = new TcpListener(IPAddress.Loopback, 0);
        ascolto.Start();
        int porta = ((IPEndPoint)ascolto.LocalEndpoint).Port;
        string? richiestaVista = null;
        var server = Task.Run(async () =>
        {
            using var cliente = await ascolto.AcceptTcpClientAsync();
            using var flusso = cliente.GetStream();
            var buffer = new byte[8192];
            int letti = await flusso.ReadAsync(buffer);
            richiestaVista = System.Text.Encoding.ASCII.GetString(buffer, 0, letti);
            var corpo = System.Text.Encoding.UTF8.GetBytes(StatoEsempio);
            var testa = System.Text.Encoding.ASCII.GetBytes($"HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: {corpo.Length}\r\nConnection: close\r\n\r\n");
            await flusso.WriteAsync(testa);
            await flusso.WriteAsync(corpo);
        });
        try
        {
            using var c = new ClientNas($"http://127.0.0.1:{porta}", "segreto");
            var r = await c.StatoAsync();
            Assert.True(r.Ok, r.Errore);
            Assert.Equal("Adesso è tempo di studio. Mancano 35 minuti.", r.Dati!.MessaggioCopertura);
            await server;
            Assert.Contains("GET /api/pc/stato HTTP/1.1", richiestaVista);
            Assert.Contains("Authorization: Bearer segreto", richiestaVista);
        }
        finally
        {
            ascolto.Stop();
        }
    }
}
