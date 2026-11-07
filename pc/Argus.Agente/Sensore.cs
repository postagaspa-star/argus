using Argus.Agente.Sistema;

namespace Argus.Agente;

/// <summary>Cosa deve fare la copertura adesso (lo decide il sensore, lo esegue il thread delle finestre).</summary>
/// <param name="Attiva">La copertura prende il primo piano (così la tastiera non va alla cosa coperta).</param>
internal sealed record DecisioneCopertura(bool Copri, string Messaggio, bool Attiva);

/// <summary>
/// Il sensore (un thread suo, non quello delle finestre): ogni 250 ms guarda la finestra in primo piano e decide
/// la copertura; ogni secondo mette un campione in coda per POST /api/pc/attivita.
/// <list type="bullet">
/// <item>se in primo piano c'è Argus stesso (terminale, copertura) o una superficie di Windows (menu Start,
/// barra, Alt+Tab), vale l'ultima finestra vera: aprire Start non scopre il video sotto;</item>
/// <item>la copertura compare dopo 1 secondo di "da coprire" continuo (niente lampi nei passaggi) e sparisce
/// subito appena in primo piano torna una cosa permessa;</item>
/// <item>se Pactum copre già, quella di Argus si fa da parte (il campione lo dice con pactum_copre);</item>
/// <item>ogni programma è riconosciuto dal percorso, non solo dal nome (<see cref="RiconoscitoreProgrammi"/>):
/// un programma non riconosciuto non è una superficie di Windows, non è un browser e non vale per le liste; al
/// NAS va come "non_riconosciuto:nome.exe".</item>
/// </list>
/// </summary>
internal sealed class Sensore : IDisposable
{
    public const int PassoMs = 250;
    public const long RitardoCoperturaMs = 1000;

    private readonly StatoAgente stato;
    private readonly Action<DecisioneCopertura> applica;
    private readonly RiconoscitoreProgrammi riconoscitore;
    private readonly Thread thread;
    private volatile bool fermo;
    private long ultimoGiroMs = Environment.TickCount64;

    public Sensore(StatoAgente stato, RiconoscitoreProgrammi riconoscitore, Action<DecisioneCopertura> applica)
    {
        this.stato = stato;
        this.riconoscitore = riconoscitore;
        this.applica = applica;
        thread = new Thread(Ciclo) { IsBackground = true, Name = "Argus sensore" };
    }

    /// <summary>Quando il sensore ha fatto l'ultimo giro (per il battito verso il guardiano).</summary>
    public long UltimoGiroMs => Interlocked.Read(ref ultimoGiroMs);

    public void Avvia() => thread.Start();

    private sealed class Osservata
    {
        public IntPtr Hwnd;
        public string Exe = "";
        public string? Percorso;
        public Riconoscimento Riconosciuto = new("", null, ComeRiconosciuto.SenzaPercorso);
        public bool SchermoIntero;
        public string? Dominio;
        public long LettoMs = long.MinValue / 2;
    }

    private void Ciclo()
    {
        var lettore = new LettoreIndirizzi();
        var giudice = new GiudiceFinestra();
        var audio = new LettoreAudio();
        var pactum = new SentinellaPactum(riconoscitore);
        Osservata? osservata = null;
        long ultimoLentoMs = long.MinValue / 2, ultimoCampioneMs = long.MinValue / 2, ultimaAttivazioneMs = long.MinValue / 2;
        long copriDalMs = -1, ultimoErroreMs = long.MinValue / 2;
        bool pactumCopre = false, bloccato = false, pactumPrima = false;
        IntPtr primoPianoPrima = IntPtr.Zero;
        DecisioneCopertura? ultimaInviata = null;

        while (!fermo)
        {
            try
            {
                long ms = Environment.TickCount64;
                Interlocked.Exchange(ref ultimoGiroMs, ms);
                var adesso = DateTimeOffset.Now;
                var modalita = stato.Modalita(adesso);
                var liste = stato.Liste;
                var verdetti = stato.Verdetti;

                if (ms - ultimoLentoMs >= 1000)
                {
                    ultimoLentoMs = ms;
                    pactumCopre = pactum.Copre();
                    bloccato = Sessione.SchermoBloccato();
                    if (pactumCopre != pactumPrima)
                    {
                        pactumPrima = pactumCopre;
                        stato.AccodaEvento(TipiEvento.PactumCopre, new() { ["attivo"] = pactumCopre });
                        Log.Info(pactumCopre ? "Pactum copre: la copertura di Argus si fa da parte" : "Pactum non copre più");
                    }
                }

                var fg = PrimoPiano.Leggi();
                // Riconosciuto dal percorso: firma, nome originale e permessi restano in memoria per percorso e data.
                var rFg = fg == null || fg.Nostra ? null : riconoscitore.Riconosci(fg.Exe, fg.Percorso);
                bool estranea = fg != null && !fg.Nostra && !SuperficiSistema.ÈNeutra(rFg?.Nome ?? "", fg.Classe);
                if (estranea)
                {
                    if (osservata == null || osservata.Hwnd != fg!.Hwnd)
                        osservata = new Osservata { Hwnd = fg!.Hwnd };
                    osservata.Exe = fg.Exe;
                    osservata.Percorso = fg.Percorso;
                    osservata.Riconosciuto = rFg!;
                    osservata.SchermoIntero = fg.SchermoIntero;
                    if (rFg!.Nome != null && liste.ÈBrowser(rFg.Nome))
                    {
                        if (ms - osservata.LettoMs >= 1000)
                        {
                            osservata.Dominio = lettore.Leggi(fg.Hwnd, rFg.Nome, fg.SchermoIntero);
                            osservata.LettoMs = ms;
                        }
                    }
                    else
                    {
                        osservata.Dominio = null;
                    }
                }
                else if (osservata != null && !Win32.IsWindow(osservata.Hwnd))
                {
                    osservata = null; // la finestra osservata non c'è più
                }

                Giudizio? giudizio = null;
                if (osservata != null)
                {
                    var o = osservata;
                    giudizio = giudice.Giudica(new InfoFinestra((long)o.Hwnd, o.Exe, o.Percorso, o.Riconosciuto), o.Dominio,
                        () => Win32.TitoloDi(o.Hwnd), liste, modalita.Modalita, verdetti, ms);
                }

                // La copertura.
                bool copri = giudizio?.DaCoprire == true && Modalitas.Copre(modalita.Modalita) && !pactumCopre && !bloccato;
                if (copri)
                {
                    if (copriDalMs < 0) copriDalMs = ms;
                }
                else
                {
                    copriDalMs = -1;
                }
                bool mostra = copri && (stato.CoperturaVisibile || ms - copriDalMs >= RitardoCoperturaMs);
                bool attiva = mostra && estranea
                              && (fg!.Hwnd != primoPianoPrima || !stato.CoperturaVisibile || ms - ultimaAttivazioneMs > 2000);
                if (attiva) ultimaAttivazioneMs = ms;
                primoPianoPrima = fg?.Hwnd ?? IntPtr.Zero;
                var messaggio = modalita.MessaggioCopertura ?? DecisoreModalita.MessaggioDiRiserva;
                var decisione = new DecisioneCopertura(mostra, messaggio, attiva);
                if (attiva || ultimaInviata == null || ultimaInviata.Copri != decisione.Copri || ultimaInviata.Messaggio != decisione.Messaggio)
                {
                    ultimaInviata = decisione;
                    applica(decisione);
                }

                // Un campione al secondo.
                if (ms - ultimoCampioneMs >= 1000)
                {
                    ultimoCampioneMs = ms;
                    var c = new Campione
                    {
                        Ts = Tempo.Iso(adesso),
                        InattivoSecondi = Sessione.SecondiInattivo(),
                        Audio = audio.Processi((exe, percorso) => riconoscitore.Riconosci(exe, percorso).NomePerNas(liste)),
                        SchermoBloccato = bloccato,
                        PactumCopre = pactumCopre,
                        Coperto = stato.CoperturaVisibile,
                        Permesso = true,
                    };
                    if ((c.Coperto || estranea) && osservata != null && giudizio != null)
                    {
                        c.Processo = osservata.Riconosciuto.NomePerNas(liste);
                        c.Dominio = giudizio.Dominio;
                        c.Titolo = giudizio.Titolo;
                        c.Permesso = giudizio.Permesso && !c.Coperto;
                    }
                    else if (fg != null)
                    {
                        // Argus stesso (terminale) o una superficie di Windows: permessi.
                        c.Processo = fg.Nostra ? PrimoPiano.MioExe : fg.Exe;
                    }
                    stato.Campioni.Aggiungi(c);
                }
            }
            catch (Exception e)
            {
                long ms = Environment.TickCount64;
                if (ms - ultimoErroreMs > 60_000)
                {
                    ultimoErroreMs = ms;
                    Log.Errore("sensore", e);
                }
            }
            Thread.Sleep(PassoMs);
        }
    }

    public void Dispose()
    {
        fermo = true;
        if (thread.IsAlive) thread.Join(2000);
    }
}
