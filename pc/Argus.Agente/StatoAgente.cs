namespace Argus.Agente;

/// <summary>
/// Quello che sanno insieme il sensore, la rete e le finestre: liste, verdetti, ultimo stato del NAS,
/// modalità, coda dei campioni e degli eventi. Tutto sotto un lucchetto.
/// </summary>
internal sealed class StatoAgente
{
    private readonly object chiave = new();
    private readonly DecisoreModalita decisore;
    private readonly string fileSblocco;
    private Liste liste = Liste.Iniziali();
    private IReadOnlyDictionary<string, string> verdetti = new Dictionary<string, string>();
    private (long Ms, bool Attivo) sblocco = (long.MinValue / 2, false);
    private ModalitaEffettiva? ultimaModalita;
    private readonly Queue<(string Tipo, Dictionary<string, object?> Dettagli, DateTimeOffset Ts)> eventi = new();

    public StatoAgente(CalendarioScolastico calendario, string fileSblocco)
    {
        decisore = new DecisoreModalita(calendario);
        this.fileSblocco = fileSblocco;
    }

    public CodaCampioni Campioni { get; } = new();

    /// <summary>La copertura di Argus è sullo schermo adesso (la scrive il thread delle finestre).</summary>
    public volatile bool CoperturaVisibile;

    public Liste Liste
    {
        get { lock (chiave) return liste; }
    }

    public IReadOnlyDictionary<string, string> Verdetti
    {
        get { lock (chiave) return verdetti; }
    }

    public void ImpostaListe(Liste nuove)
    {
        lock (chiave) liste = nuove;
    }

    public StatoNas? UltimoStato
    {
        get { lock (chiave) return decisore.UltimoStato; }
    }

    public DateTimeOffset? UltimaRisposta
    {
        get { lock (chiave) return decisore.UltimaRisposta; }
    }

    public void RegistraStato(StatoNas stato, DateTimeOffset adesso)
    {
        lock (chiave)
        {
            decisore.RegistraRisposta(stato, adesso);
            verdetti = stato.Verdetti ?? new Dictionary<string, string>();
        }
    }

    /// <summary>La modalità che vale adesso (NAS, sblocco d'emergenza, regola "senza NAS").</summary>
    public ModalitaEffettiva Modalita(DateTimeOffset adesso)
    {
        bool sbloccoAttivo = SbloccoAttivo(adesso);
        lock (chiave)
        {
            var m = decisore.Calcola(adesso, sbloccoAttivo);
            if (ultimaModalita == null || ultimaModalita.Modalita != m.Modalita || ultimaModalita.Motivo != m.Motivo)
                Log.Info($"modalità: {Modalitas.Testo(m.Modalita)} ({m.Motivo})");
            ultimaModalita = m;
            return m;
        }
    }

    /// <summary>Lo sblocco d'emergenza dal file (riletto al massimo ogni 5 secondi).</summary>
    private bool SbloccoAttivo(DateTimeOffset adesso)
    {
        long ms = Environment.TickCount64;
        lock (chiave)
        {
            if (ms - sblocco.Ms < 5000) return sblocco.Attivo;
        }
        bool attivo = Sblocco.AttivoNelFile(fileSblocco, adesso);
        lock (chiave) sblocco = (ms, attivo);
        return attivo;
    }

    public void AccodaEvento(string tipo, Dictionary<string, object?> dettagli)
    {
        lock (chiave)
        {
            eventi.Enqueue((tipo, dettagli, DateTimeOffset.Now));
            while (eventi.Count > 50) eventi.Dequeue();
        }
    }

    public bool PrendiEvento(out (string Tipo, Dictionary<string, object?> Dettagli, DateTimeOffset Ts) evento)
    {
        lock (chiave) return eventi.TryPeek(out evento);
    }

    public void TogliEvento()
    {
        lock (chiave) eventi.TryDequeue(out _);
    }
}
