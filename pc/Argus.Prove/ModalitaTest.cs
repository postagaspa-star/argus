using Argus.Nucleo;

namespace Argus.Prove;

public class CalendarioTest
{
    private static readonly CalendarioScolastico C = new();

    [Theory]
    [InlineData("2026-09-09", false)] // prima dell'inizio
    [InlineData("2026-09-10", true)]  // primo giorno (giovedì)
    [InlineData("2026-10-29", true)]
    [InlineData("2026-10-30", false)]
    [InlineData("2026-11-02", false)]
    [InlineData("2026-11-03", true)]
    [InlineData("2026-11-09", true)]  // lunedì
    [InlineData("2026-11-07", false)] // sabato
    [InlineData("2026-11-08", false)] // domenica
    [InlineData("2026-12-07", false)]
    [InlineData("2026-12-08", false)]
    [InlineData("2026-12-23", true)]
    [InlineData("2026-12-24", false)]
    [InlineData("2027-01-06", false)]
    [InlineData("2027-01-07", true)]
    [InlineData("2027-02-08", false)]
    [InlineData("2027-02-12", false)]
    [InlineData("2027-02-15", true)]
    [InlineData("2027-03-25", false)]
    [InlineData("2027-03-30", false)]
    [InlineData("2027-03-31", true)]
    [InlineData("2027-04-29", false)]
    [InlineData("2027-04-30", false)]
    [InlineData("2027-05-31", false)]
    [InlineData("2027-06-02", false)]
    [InlineData("2027-06-03", true)]
    [InlineData("2027-06-08", true)]  // ultimo giorno
    [InlineData("2027-06-09", false)]
    [InlineData("2027-07-15", false)]
    public void Anno2026_27(string data, bool atteso) =>
        Assert.Equal(atteso, C.ÈGiornoDiScuola(DateOnly.Parse(data)));

    [Fact]
    public void SabatoConfigurabile()
    {
        var sabato = DateOnly.Parse("2026-11-14");
        Assert.False(new CalendarioScolastico().ÈGiornoDiScuola(sabato));
        Assert.True(new CalendarioScolastico(sabatoScuola: true).ÈGiornoDiScuola(sabato));
        Assert.False(new CalendarioScolastico(sabatoScuola: true).ÈGiornoDiScuola(DateOnly.Parse("2026-10-31")));
    }

    [Fact]
    public void Patrono()
    {
        var c = new CalendarioScolastico(patrono: "11/11");
        Assert.False(c.ÈGiornoDiScuola(DateOnly.Parse("2026-11-11")));
        Assert.True(c.ÈGiornoDiScuola(DateOnly.Parse("2026-11-12")));
        var d = new CalendarioScolastico(patrono: "2026-11-12");
        Assert.False(d.ÈGiornoDiScuola(DateOnly.Parse("2026-11-12")));
        Assert.True(new CalendarioScolastico(patrono: "boh").ÈGiornoDiScuola(DateOnly.Parse("2026-11-12")));
    }

    [Fact]
    public void Pasqua()
    {
        Assert.Equal(new DateOnly(2027, 3, 28), CalendarioScolastico.Pasqua(2027));
        Assert.Equal(new DateOnly(2028, 4, 16), CalendarioScolastico.Pasqua(2028));
        Assert.Equal(new DateOnly(2026, 4, 5), CalendarioScolastico.Pasqua(2026));
    }

    [Theory]
    [InlineData("2027-09-13", true)]  // anno senza tabella: regola generica
    [InlineData("2027-12-27", false)]
    [InlineData("2028-04-13", false)] // giovedì prima di Pasqua 2028
    [InlineData("2028-04-19", true)]
    [InlineData("2028-07-03", false)]
    public void AnniDopo(string data, bool atteso) =>
        Assert.Equal(atteso, C.ÈGiornoDiScuola(DateOnly.Parse(data)));
}

public class DecisoreModalitaTest
{
    private static StatoNas Stato(string modalita, bool quotaFatta = false, string? ora = null) => new()
    {
        OraServer = ora,
        Modalita = modalita,
        MessaggioCopertura = "Adesso è tempo di studio. Mancano 35 minuti.",
        QuotaFattaOggi = quotaFatta,
    };

    private static DecisoreModalita Nuovo() => new(new CalendarioScolastico());

    [Fact]
    public void ConIlNasValeQuelloCheDice()
    {
        var d = Nuovo();
        d.RegistraRisposta(Stato("lavoro"), Dati.Lunedi(15));
        var m = d.Calcola(Dati.Lunedi(15).AddSeconds(5), false);
        Assert.Equal(Modalita.Lavoro, m.Modalita);
        Assert.Equal("nas", m.Motivo);
        Assert.False(m.NasMuto);
        Assert.Equal("Adesso è tempo di studio. Mancano 35 minuti.", m.MessaggioCopertura);
    }

    [Fact]
    public void EntroDueMinutiValeAncoraIlNas()
    {
        var d = Nuovo();
        d.RegistraRisposta(Stato("libero"), Dati.Lunedi(15));
        Assert.Equal(Modalita.Libero, d.Calcola(Dati.Lunedi(15).AddSeconds(119), false).Modalita);
    }

    [Fact]
    public void NasMutoDaPiuDiDueMinutiDopoLe13DiUnGiornoDiScuola_Studio()
    {
        var d = Nuovo();
        d.RegistraRisposta(Stato("libero"), Dati.Lunedi(15));
        var m = d.Calcola(Dati.Lunedi(15).AddSeconds(121), false);
        Assert.Equal(Modalita.Studio, m.Modalita);
        Assert.Equal("senza_nas", m.Motivo);
        Assert.True(m.NasMuto);
        Assert.False(string.IsNullOrEmpty(m.MessaggioCopertura));
    }

    [Fact]
    public void QuotaFattaOggi_ResteLibero()
    {
        var d = Nuovo();
        d.RegistraRisposta(Stato("libero", quotaFatta: true, ora: "2026-11-09T15:00:00+01:00"), Dati.Lunedi(15));
        var m = d.Calcola(Dati.Lunedi(18), false);
        Assert.Equal(Modalita.Libero, m.Modalita);
        Assert.Equal("senza_nas_quota_fatta", m.Motivo);
    }

    [Fact]
    public void QuotaFattaIeri_NonConta()
    {
        var d = Nuovo();
        var venerdi = new DateOnly(2026, 11, 6);
        d.RegistraRisposta(Stato("libero", quotaFatta: true, ora: "2026-11-06T20:00:00+01:00"), new DateTimeOffset(2026, 11, 6, 20, 0, 0, TimeSpan.FromHours(1)));
        Assert.Equal(Modalita.Studio, d.Calcola(Dati.Lunedi(14), false).Modalita);
        _ = venerdi;
    }

    [Fact]
    public void PrimaDelle11_Libero()
    {
        var d = Nuovo();
        Assert.Equal(Modalita.Libero, d.Calcola(Dati.Lunedi(10, 59), false).Modalita);
        Assert.Equal(Modalita.Studio, d.Calcola(Dati.Lunedi(11, 0), false).Modalita);
        Assert.Equal(Modalita.Studio, d.Calcola(Dati.Lunedi(12, 30), false).Modalita); // prima era libero (finestra dalle 13)
        Assert.Equal(Modalita.Studio, d.Calcola(Dati.Lunedi(23, 59), false).Modalita);
    }

    [Fact]
    public void MaiRispostoDentroLaFinestra_SubitoStudio()
    {
        var m = Nuovo().Calcola(Dati.Lunedi(16), false);
        Assert.Equal(Modalita.Studio, m.Modalita);
        Assert.True(m.NasMuto);
    }

    [Fact]
    public void FineSettimanaEVacanze_Libero()
    {
        var d = Nuovo();
        Assert.Equal(Modalita.Libero, d.Calcola(new DateTimeOffset(2026, 11, 8, 16, 0, 0, TimeSpan.FromHours(1)), false).Modalita);
        Assert.Equal(Modalita.Libero, d.Calcola(new DateTimeOffset(2026, 12, 28, 16, 0, 0, TimeSpan.FromHours(1)), false).Modalita);
    }

    [Fact]
    public void LOraConta_InItalia()
    {
        // 12:30 UTC = 13:30 in Italia (inverno): dentro la finestra.
        var m = Nuovo().Calcola(new DateTimeOffset(2026, 11, 9, 12, 30, 0, TimeSpan.Zero), false);
        Assert.Equal(Modalita.Studio, m.Modalita);
    }

    [Fact]
    public void SbloccoVinceSuTutto()
    {
        var d = Nuovo();
        d.RegistraRisposta(Stato("studio"), Dati.Lunedi(15));
        Assert.Equal(Modalita.Libero, d.Calcola(Dati.Lunedi(15), true).Modalita);
        Assert.Equal(Modalita.Libero, Nuovo().Calcola(Dati.Lunedi(16), true).Modalita);
    }

    [Fact]
    public void SbloccoDettoDalNas()
    {
        var d = Nuovo();
        var s = Stato("studio");
        s.SbloccoFino = "2026-11-09T19:00:00+01:00";
        d.RegistraRisposta(s, Dati.Lunedi(15));
        Assert.Equal(Modalita.Libero, d.Calcola(Dati.Lunedi(15), false).Modalita);
    }

    [Fact]
    public void ModalitaSconosciuta_Studio()
    {
        var d = Nuovo();
        d.RegistraRisposta(Stato("vacanza"), Dati.Lunedi(10));
        Assert.Equal(Modalita.Studio, d.Calcola(Dati.Lunedi(10), false).Modalita);
    }

    [Fact]
    public void InattivoDalNas()
    {
        var d = Nuovo();
        d.RegistraRisposta(Stato("inattivo"), Dati.Lunedi(15));
        var m = d.Calcola(Dati.Lunedi(15), false);
        Assert.Equal(Modalita.Inattivo, m.Modalita);
        Assert.False(Modalitas.Copre(m.Modalita));
    }

    [Fact]
    public void OrologioTornatoIndietro_NasMuto()
    {
        var d = Nuovo();
        d.RegistraRisposta(Stato("libero"), Dati.Lunedi(16));
        Assert.True(d.NasMuto(Dati.Lunedi(15)));
    }
}

public class SbloccoTest
{
    [Fact]
    public void NuovoValePerLeOreDate()
    {
        var s = Sblocco.Nuovo(4, Dati.Lunedi(15));
        Assert.True(s.Attivo(Dati.Lunedi(15)));
        Assert.True(s.Attivo(Dati.Lunedi(18, 59)));
        Assert.False(s.Attivo(Dati.Lunedi(19)));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(49)]
    [InlineData(-1)]
    public void OreFuoriDa1a48(int ore) => Assert.Throws<ArgumentOutOfRangeException>(() => Sblocco.Nuovo(ore, Dati.Lunedi(15)));

    [Fact]
    public void ToltoNonVale() => Assert.False(Sblocco.Tolto(Dati.Lunedi(15)).Attivo(Dati.Lunedi(15)));

    [Fact]
    public void FileCambiatoAManoNonVale()
    {
        var s = Sblocco.Nuovo(2, Dati.Lunedi(15));
        s.Fino = Tempo.Iso(Dati.Lunedi(15).AddHours(30)); // durata incoerente con le ore
        Assert.False(s.Attivo(Dati.Lunedi(16)));
        var futuro = Sblocco.Nuovo(2, Dati.Lunedi(18)); // creato "nel futuro": orologio spostato indietro
        Assert.False(futuro.Attivo(Dati.Lunedi(15)));
    }

    [Fact]
    public void FileAndataERitorno()
    {
        var cartella = Path.Combine(Path.GetTempPath(), "argus-prove-" + Guid.NewGuid().ToString("N"));
        try
        {
            var file = Path.Combine(cartella, "sblocco.json");
            Assert.Null(Sblocco.Leggi(file));
            var s = Sblocco.Nuovo(8, DateTimeOffset.Now);
            FileSicuri.ScriviAtomico(file, s.InJson());
            var letto = Sblocco.Leggi(file);
            Assert.NotNull(letto);
            Assert.Equal(8, letto!.Ore);
            Assert.True(Sblocco.AttivoNelFile(file, DateTimeOffset.Now));
            File.WriteAllText(file, "{ rovinato");
            Assert.Null(Sblocco.Leggi(file));
            Assert.False(Sblocco.AttivoNelFile(file, DateTimeOffset.Now));
        }
        finally
        {
            Directory.Delete(cartella, true);
        }
    }

    [Fact]
    public void DettagliDellEvento()
    {
        var s = Sblocco.Nuovo(4, Dati.Lunedi(15));
        var d = s.DettagliEvento();
        Assert.Equal(4, d["ore"]);
        Assert.False(d.ContainsKey("fino")); // la fine la calcola il NAS
        Assert.Single(d);
        Assert.Equal(0, Sblocco.Tolto(Dati.Lunedi(15)).DettagliEvento()["ore"]);
    }
}

public class ConfigTest
{
    [Fact]
    public void LeggeConfigConValoriDiSerie()
    {
        var c = ConfigArgus.DaJson("""{"nas_url": "http://nas.locale:8700", "token": "abc", "utente_controllato": "studente"}""");
        Assert.Equal("http://nas.locale:8700", c.NasUrl);
        Assert.Equal("studente", c.UtenteControllato);
        Assert.Null(c.ProblemaNas());
        Assert.Equal(8781, c.Motore.Porta);
        Assert.Equal("llama.cpp-win-x86_64-avx2-", c.Motore.PrefissoBackend);
        Assert.Equal(5, c.Motore.MinutiSpegnimento);
        Assert.EndsWith("Qwen3.5-9B-Q4_K_M.gguf", c.Motore.Modello);
        Assert.True(c.Motore.ThreadEffettivi() >= 1);
    }

    [Fact]
    public void ProblemiInItaliano()
    {
        Assert.Equal("Manca l'indirizzo del NAS.", new ConfigArgus().ProblemaNas());
        Assert.Contains("non è valido", new ConfigArgus { NasUrl = "ftp://x", Token = "a" }.ProblemaNas());
        Assert.Equal("Manca il token del PC.", new ConfigArgus { NasUrl = "http://x:8700" }.ProblemaNas());
        // Una configurazione giusta non deve sembrare "mancante" (errore trovato nella prova vera dell'agente).
        Assert.Null(ConfigArgus.Problema(new ConfigArgus { NasUrl = "http://x:8700", Token = "a" }));
        Assert.Equal("manca la configurazione", ConfigArgus.Problema(null));
        Assert.Throws<ErroreConfig>(() => ConfigArgus.DaJson("{ rotto"));
    }

    [Fact]
    public void AndataERitorno()
    {
        var c = new ConfigArgus { NasUrl = "http://nas:8700", Token = "t", Motore = new ConfigMotore { Porta = 9999, Thread = 3 } };
        var d = ConfigArgus.DaJson(c.InJson());
        Assert.Equal(9999, d.Motore.Porta);
        Assert.Equal(3, d.Motore.ThreadEffettivi());
        Assert.Contains("\"nas_url\"", c.InJson());
    }
}
