using System.Security.Principal;
using System.Windows.Forms;

namespace Argus.Agente;

/// <summary>
/// Il battito verso il guardiano (revisione B6): un byte ogni 5 secondi sull'uscita standard, che è una conduttura
/// anonima del guardiano (nessun altro processo può aprirla per battere al posto dell'agente). Il byte parte solo se
/// negli ultimi 10 secondi hanno girato sia il thread delle finestre (copertura, terminale) sia il sensore: se
/// l'agente viene sospeso, si blocca o perde la finestra-ponte, il battito si ferma e dopo 20 secondi il guardiano lo
/// chiude e lo riapre. A ogni giro rimette anche i permessi stretti ai suoi thread (i thread nuovi nascono con i
/// permessi di serie dell'utente).
/// </summary>
internal sealed class BattitoAgente : IDisposable
{
    private readonly Stream uscita;
    private readonly Control ponte;
    private readonly Func<long> ultimoGiroSensore;
    private readonly string sidUtente;
    private readonly Thread thread;
    private long finestreMs = Environment.TickCount64;
    private volatile bool fermo;

    public BattitoAgente(Stream uscita, Control ponte, Func<long> ultimoGiroSensore)
    {
        this.uscita = uscita;
        this.ponte = ponte;
        this.ultimoGiroSensore = ultimoGiroSensore;
        sidUtente = WindowsIdentity.GetCurrent().User!.Value;
        thread = new Thread(Ciclo) { IsBackground = true, Name = "Argus battito" };
    }

    public void Avvia() => thread.Start();

    private void Ciclo()
    {
        long prossimo = 0;
        bool avvisato = false;
        while (!fermo)
        {
            long ms = Environment.TickCount64;
            try
            {
                // Il thread delle finestre è vivo se esegue questo entro 10 secondi.
                ponte.BeginInvoke(() => Interlocked.Exchange(ref finestreMs, Environment.TickCount64));
            }
            catch (Exception e) when (e is InvalidOperationException or ObjectDisposedException)
            {
            }
            if (ms >= prossimo)
            {
                prossimo = ms + RegoleBattito.OgniMs;
                try
                {
                    SicurezzaAgente.ProteggiThreadDelProcesso(sidUtente);
                }
                catch (Exception e)
                {
                    if (!avvisato) Log.Errore("permessi dei thread", e);
                    avvisato = true;
                }
                long finestre = ms - Interlocked.Read(ref finestreMs), sensore = ms - ultimoGiroSensore();
                if (finestre <= RegoleBattito.VivoEntroMs && sensore <= RegoleBattito.VivoEntroMs)
                {
                    try
                    {
                        uscita.WriteByte(1);
                        uscita.Flush();
                    }
                    catch (Exception e) when (e is IOException or ObjectDisposedException or NotSupportedException)
                    {
                        Log.Avviso("battito: il guardiano non ascolta più (" + e.Message + ")");
                        return;
                    }
                }
                else
                {
                    Log.Avviso($"battito saltato: finestre ferme da {finestre / 1000} s, sensore da {sensore / 1000} s");
                }
            }
            Thread.Sleep(1000);
        }
    }

    public void Dispose()
    {
        fermo = true;
    }
}
