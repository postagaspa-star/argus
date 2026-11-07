namespace Argus.Nucleo;

/// <summary>La modalità che vale adesso sul PC, e perché.</summary>
/// <param name="Motivo">"nas", "sblocco", "senza_nas", "senza_nas_quota_fatta", "senza_nas_fuori_orario".</param>
/// <param name="NasMuto">Il NAS non risponde da più di 2 minuti (o non ha mai risposto).</param>
public sealed record ModalitaEffettiva(Modalita Modalita, string Motivo, bool NasMuto, string? MessaggioCopertura);

/// <summary>
/// Decide la modalità del PC da quello che dice il NAS, dallo sblocco d'emergenza e dalla regola "senza NAS"
/// (regole 12): in un giorno di scuola tra le 11:00 e mezzanotte, se il NAS non risponde da più di 2 minuti e
/// l'ultima risposta non era "quota fatta oggi", il PC va in modalità studio finché il NAS torna.
///
/// Letture prudenti (scritte in NOTE-COSTRUTTORE.md):
/// <list type="bullet">
/// <item>se il NAS non ha mai risposto da quando l'agente è partito, vale come muto: dentro la finestra
/// (giorno di scuola, 11:00-24:00) si è subito in studio, senza aspettare 2 minuti (altrimenti chiudere e
/// riaprire l'agente regalerebbe 2 minuti ogni volta);</item>
/// <item>"quota fatta oggi" conta solo se l'ultima risposta è dello stesso giorno (in Italia);</item>
/// <item>fuori dalla finestra, col NAS muto, il PC è libero: la regola copre solo quella finestra;</item>
/// <item>entro 2 minuti dall'ultima risposta vale ancora la modalità detta dal NAS.</item>
/// </list>
/// Non è thread-safe: chi la usa da più thread mette un lucchetto.
/// </summary>
public sealed class DecisoreModalita
{
    public static readonly TimeSpan SogliaSilenzio = TimeSpan.FromMinutes(2);
    public static readonly TimeSpan InizioFinestra = TimeSpan.FromHours(11); // regole 12: dalle 11:00, l'ora da cui può esserci l'arrivo

    public const string MessaggioSenzaNas = "Adesso è tempo di studio.";
    public const string MessaggioDiRiserva = "Adesso è tempo di studio.";

    private readonly CalendarioScolastico calendario;
    private StatoNas? ultimo;
    private DateTimeOffset? ultimaRisposta;
    private DateOnly? giornoUltima;

    public DecisoreModalita(CalendarioScolastico calendario)
    {
        this.calendario = calendario;
    }

    public StatoNas? UltimoStato => ultimo;
    public DateTimeOffset? UltimaRisposta => ultimaRisposta;

    /// <summary>Il NAS ha risposto a GET /api/pc/stato.</summary>
    public void RegistraRisposta(StatoNas stato, DateTimeOffset adesso)
    {
        ultimo = stato;
        ultimaRisposta = adesso;
        // Il giorno della risposta: quello del NAS (l'orologio che conta), altrimenti quello del PC.
        var oraServer = Tempo.Leggi(stato.OraServer) ?? adesso;
        giornoUltima = DateOnly.FromDateTime(Tempo.OraItaliana(oraServer));
    }

    public bool NasMuto(DateTimeOffset adesso) =>
        ultimaRisposta is not DateTimeOffset u
        || adesso - u > SogliaSilenzio
        || u - adesso > TimeSpan.FromMinutes(5); // orologio tornato indietro: non ci si fida

    public ModalitaEffettiva Calcola(DateTimeOffset adesso, bool sbloccoAttivo)
    {
        bool muto = NasMuto(adesso);
        if (sbloccoAttivo) return new ModalitaEffettiva(Modalita.Libero, "sblocco", muto, null);

        if (!muto && ultimo != null)
        {
            if (Tempo.Leggi(ultimo.SbloccoFino) is DateTimeOffset fino && fino > adesso)
                return new ModalitaEffettiva(Modalita.Libero, "sblocco", false, null);
            var m = Modalitas.DaTesto(ultimo.Modalita);
            var messaggio = string.IsNullOrWhiteSpace(ultimo.MessaggioCopertura) ? MessaggioDiRiserva : ultimo.MessaggioCopertura!.Trim();
            return new ModalitaEffettiva(m, "nas", false, messaggio);
        }

        // Il NAS non risponde (o non ha mai risposto): regole 12, "senza NAS".
        var ora = Tempo.OraItaliana(adesso);
        var oggi = DateOnly.FromDateTime(ora);
        if (calendario.ÈGiornoDiScuola(oggi) && ora.TimeOfDay >= InizioFinestra)
        {
            if (ultimo?.QuotaFattaOggi == true && giornoUltima == oggi)
                return new ModalitaEffettiva(Modalita.Libero, "senza_nas_quota_fatta", true, null);
            return new ModalitaEffettiva(Modalita.Studio, "senza_nas", true, MessaggioSenzaNas);
        }
        return new ModalitaEffettiva(Modalita.Libero, "senza_nas_fuori_orario", true, null);
    }
}
