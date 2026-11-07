namespace Argus.Agente;

/// <summary>
/// I giri verso il NAS (contratto, sezione 3): stato ogni 2 secondi, attività ogni 5, liste quando cambia la
/// versione, eventi in coda, voce di ripiego (riprodotta una volta). Se il NAS non risponde si va avanti:
/// la modalità la decide la regola "senza NAS" (StatoAgente).
/// </summary>
internal sealed class ReteAgente : IDisposable
{
    private readonly ClientNas nas;
    private readonly StatoAgente stato;
    private readonly Action<byte[]> riproduci;
    private readonly CancellationTokenSource fine = new();
    private readonly HashSet<string> vociSentite = new(StringComparer.Ordinal);
    private DateTimeOffset? mutoDal;
    private bool erroreTokenScritto;
    private int versioneListe = -1;
    private bool listeInCarico;

    public ReteAgente(ClientNas nas, StatoAgente stato, Action<byte[]> riproduci)
    {
        this.nas = nas;
        this.stato = stato;
        this.riproduci = riproduci;
    }

    public ClientNas Client => nas;

    public void Avvia()
    {
        _ = Task.Run(() => Giro("stato", TimeSpan.FromSeconds(2), GiroStatoAsync));
        _ = Task.Run(() => Giro("attività", TimeSpan.FromSeconds(5), GiroAttivitaAsync));
        _ = Task.Run(() => Giro("eventi", TimeSpan.FromSeconds(3), GiroEventiAsync));
    }

    private async Task Giro(string nome, TimeSpan passo, Func<CancellationToken, Task> lavoro)
    {
        var ct = fine.Token;
        long ultimoErrore = long.MinValue / 2;
        while (!ct.IsCancellationRequested)
        {
            try
            {
                await lavoro(ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception e)
            {
                if (Environment.TickCount64 - ultimoErrore > 60_000)
                {
                    ultimoErrore = Environment.TickCount64;
                    Log.Errore("giro " + nome, e);
                }
            }
            try
            {
                await Task.Delay(passo, ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                break;
            }
        }
    }

    private async Task GiroStatoAsync(CancellationToken ct)
    {
        var r = await nas.StatoAsync(ct).ConfigureAwait(false);
        var adesso = DateTimeOffset.Now;
        if (r.Ok && r.Dati != null)
        {
            stato.RegistraStato(r.Dati, adesso);
            erroreTokenScritto = false;
            if (mutoDal is DateTimeOffset dal)
            {
                mutoDal = null;
                var secondi = (int)(adesso - dal).TotalSeconds;
                Log.Info($"il NAS risponde di nuovo (muto per {secondi} s)");
                if (adesso - dal > DecisoreModalita.SogliaSilenzio)
                    stato.AccodaEvento(TipiEvento.NasIrraggiungibile, new() { ["dal"] = Tempo.Iso(dal), ["al"] = Tempo.Iso(adesso), ["secondi"] = secondi });
            }
            if (r.Dati.ListeVersione != versioneListe && !listeInCarico) _ = CaricaListeAsync(r.Dati.ListeVersione, ct);
            if (r.Dati.DiVoce is { Id: { Length: > 0 } id, Url: { Length: > 0 } url } && vociSentite.Add(id))
            {
                if (vociSentite.Count > 200) vociSentite.Clear();
                _ = VoceAsync(url, ct);
            }
            return;
        }
        // Il NAS non risponde, o rifiuta il token: per la regola "senza NAS" è lo stesso.
        if (mutoDal == null)
        {
            mutoDal = adesso;
            Log.Avviso($"il NAS non dà lo stato: {r.Errore} ({r.Codice})");
        }
        if (r.Stato == 401 && !erroreTokenScritto)
        {
            erroreTokenScritto = true;
            Log.Errore("il NAS rifiuta il token di questo PC: va rifatta l'installazione con il token giusto");
        }
    }

    private async Task CaricaListeAsync(int versione, CancellationToken ct)
    {
        listeInCarico = true;
        try
        {
            var r = await nas.ListeAsync(ct).ConfigureAwait(false);
            if (r.Ok && r.Dati != null)
            {
                stato.ImpostaListe(r.Dati);
                versioneListe = versione;
                Log.Info($"liste caricate (versione {r.Dati.Versione})");
            }
            else
            {
                Log.Avviso($"liste non caricate: {r.Errore}");
            }
        }
        finally
        {
            listeInCarico = false;
        }
    }

    private async Task GiroAttivitaAsync(CancellationToken ct)
    {
        var campioni = stato.Campioni.Preleva();
        if (campioni.Count == 0) return;
        var r = await nas.AttivitaAsync(campioni, ct).ConfigureAwait(false);
        if (!r.Ok) stato.Campioni.Rimetti(campioni);
    }

    private async Task GiroEventiAsync(CancellationToken ct)
    {
        while (stato.PrendiEvento(out var e))
        {
            var r = await nas.EventoAsync(e.Tipo, e.Dettagli, e.Ts, ct).ConfigureAwait(false);
            if (!r.Ok && !r.Raggiunto) return; // si riprova al prossimo giro
            if (!r.Ok) Log.Avviso($"evento {e.Tipo} rifiutato dal NAS: {r.Errore}");
            stato.TogliEvento();
        }
    }

    private async Task VoceAsync(string url, CancellationToken ct)
    {
        for (int tentativo = 0; tentativo < 3; tentativo++)
        {
            var r = await nas.VoceAsync(url, ct).ConfigureAwait(false);
            if (r.Ok && r.Dati is { Length: > 44 } wav)
            {
                riproduci(wav);
                return;
            }
            if (r.Codice == "indirizzo") break;
            await Task.Delay(2000, ct).ConfigureAwait(false);
        }
        Log.Avviso("voce di ripiego non scaricata");
    }

    public void Dispose()
    {
        fine.Cancel();
        fine.Dispose();
    }
}
