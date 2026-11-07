using System.Text.Json;
using System.Text.Json.Serialization;

namespace Argus.Nucleo;

/// <summary>Le modalità del PC (regole 12).</summary>
public enum Modalita
{
    Libero,
    Studio,
    Lavoro,
    Inattivo,
}

public static class Modalitas
{
    /// <summary>Dal testo del NAS. Un valore sconosciuto vale "studio": nel dubbio la più severa (regole 12).</summary>
    public static Modalita DaTesto(string? testo) => (testo ?? "").Trim().ToLowerInvariant() switch
    {
        "libero" => Modalita.Libero,
        "studio" => Modalita.Studio,
        "lavoro" => Modalita.Lavoro,
        "inattivo" => Modalita.Inattivo,
        _ => Modalita.Studio,
    };

    public static string Testo(Modalita m) => m switch
    {
        Modalita.Libero => "libero",
        Modalita.Studio => "studio",
        Modalita.Lavoro => "lavoro",
        _ => "inattivo",
    };

    /// <summary>Solo in studio e lavoro si copre.</summary>
    public static bool Copre(Modalita m) => m is Modalita.Studio or Modalita.Lavoro;
}

// ---------------------------------------------------------------- GET /api/pc/stato

public sealed class StatoNas
{
    public string? OraServer { get; set; }
    public string? Modalita { get; set; }
    public int ListeVersione { get; set; }
    public QuotaNas? Quota { get; set; }
    public string? ClasseAdesso { get; set; }
    public ComandoAttivo? ComandoAttivo { get; set; }
    public Dictionary<string, string>? Verdetti { get; set; }
    public string? MessaggioCopertura { get; set; }
    public string? SbloccoFino { get; set; }
    public bool QuotaFattaOggi { get; set; }
    public DiVoce? DiVoce { get; set; }
}

public sealed class QuotaNas
{
    public double Fatti { get; set; }
    public double Totale { get; set; }
    public double Sospeso { get; set; }
    public double Aggiunte { get; set; }
    public double PausaDisponibile { get; set; }
    public string? FinePrevista { get; set; }
}

public sealed class ComandoAttivo
{
    public string? Tipo { get; set; }
    public string? Fino { get; set; }
}

public sealed class DiVoce
{
    public string? Id { get; set; }
    public string? Url { get; set; }
}

// ---------------------------------------------------------------- POST /api/pc/attivita

public sealed class Campione
{
    public string Ts { get; set; } = "";
    public string? Processo { get; set; }
    public string? Titolo { get; set; }
    public string? Dominio { get; set; }
    public bool Permesso { get; set; }
    public bool Coperto { get; set; }
    public int InattivoSecondi { get; set; }
    public List<string> Audio { get; set; } = new();
    public bool SchermoBloccato { get; set; }
    public bool PactumCopre { get; set; }
}

public sealed class CorpoAttivita
{
    public List<Campione> Campioni { get; set; } = new();
}

// ---------------------------------------------------------------- POST /api/pc/comando e /api/pc/foto

public sealed class CorpoComando
{
    public string Testo { get; set; } = "";
}

public sealed class RispostaComando
{
    public bool Ok { get; set; }
    public string? Risposta { get; set; }
    public ChiedeFoto? ChiedeFoto { get; set; }
}

public sealed class ChiedeFoto
{
    public string? Tipo { get; set; }
    public string? Nome { get; set; }
    public int Scatti { get; set; }
    public string? Consiglio { get; set; }
}

public sealed class RispostaFoto
{
    public bool Ok { get; set; }
    public string? Risposta { get; set; }
}

/// <summary>Un'immagine da mandare con POST /api/pc/foto.</summary>
public sealed record ImmagineFoto(byte[] Dati, string TipoMime);

// ---------------------------------------------------------------- GET /api/pc/lavori e POST /api/pc/lavori/{id}

public sealed class Lavoro
{
    public string Id { get; set; } = "";

    [JsonPropertyName("immagine_jpeg_base64")]
    public string? ImmagineJpegBase64 { get; set; }

    public string? Contesto { get; set; }
    public List<DomandaLavoro> Domande { get; set; } = new();
    public string? Scade { get; set; }
}

public sealed class DomandaLavoro
{
    public string Id { get; set; } = "";
    public string Domanda { get; set; } = "";
    public List<string> Opzioni { get; set; } = new();
}

public sealed class RispostaLavoro
{
    public Dictionary<string, string> Risposte { get; set; } = new();
    public long Millisecondi { get; set; }
    public string Modello { get; set; } = "";
}

// ---------------------------------------------------------------- POST /api/pc/evento

public static class TipiEvento
{
    public const string AgenteAvviato = "agente_avviato";
    public const string AgenteRiaperto = "agente_riaperto";
    public const string AgenteChiuso = "agente_chiuso";

    /// <summary>
    /// L'agente non batteva più (sospeso o bloccato): il guardiano l'ha chiuso e lo riapre. Dettagli
    /// <c>{"pid": 1234, "secondi": 21}</c>. Revisione B6: il NAS e il contratto non lo conoscono ancora (422).
    /// </summary>
    public const string AgenteBloccato = "agente_bloccato";
    public const string SbloccoEmergenza = "sblocco_emergenza";
    public const string PactumCopre = "pactum_copre";
    public const string NasIrraggiungibile = "nas_irraggiungibile";
}

public sealed class Evento
{
    public string Tipo { get; set; } = "";
    public Dictionary<string, object?> Dettagli { get; set; } = new();
    public string Ts { get; set; } = "";
}

// ---------------------------------------------------------------- generiche

public sealed class RispostaOk
{
    public bool Ok { get; set; }
}

public sealed class ErroreNas
{
    public string? Errore { get; set; }
    public string? Codice { get; set; }
}

public sealed class SaluteNas
{
    public bool Ok { get; set; }
    public string? Versione { get; set; }
    public Dictionary<string, JsonElement>? Telecamere { get; set; }
    public string? Decisore { get; set; }
    public string? Voci { get; set; }
}
