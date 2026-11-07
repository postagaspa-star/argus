using System.Net;
using System.Text;
using Argus.Nucleo;

namespace Argus.Prove;

/// <summary>Un orologio che va avanti solo quando lo dice la prova.</summary>
public sealed class OrologioFinto : IOrologio
{
    public OrologioFinto(DateTimeOffset inizio)
    {
        Adesso = inizio;
    }

    public DateTimeOffset Adesso { get; private set; }
    public long Ms { get; private set; } = 1_000_000;

    public void Avanza(TimeSpan t)
    {
        Adesso += t;
        Ms += (long)t.TotalMilliseconds;
    }
}

/// <summary>Il server finto del NAS: risponde con la funzione data e tiene le richieste ricevute.</summary>
public sealed class NasFinto : HttpMessageHandler
{
    public sealed record Richiesta(HttpMethod Metodo, string Percorso, string? Autorizzazione, string? Corpo, string? TipoContenuto,
        string? SegretoSblocco = null);

    public List<Richiesta> Richieste { get; } = new();
    public Func<Richiesta, HttpResponseMessage> Risposta { get; set; } = _ => Json("{\"ok\": true}");

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        string? corpo = request.Content == null ? null : await request.Content.ReadAsStringAsync(cancellationToken);
        var r = new Richiesta(request.Method, request.RequestUri!.AbsolutePath, request.Headers.Authorization?.ToString(), corpo,
            request.Content?.Headers.ContentType?.MediaType,
            request.Headers.TryGetValues("X-Argus-Sblocco", out var s) ? string.Join(",", s) : null);
        lock (Richieste) Richieste.Add(r);
        return Risposta(r);
    }

    public static HttpResponseMessage Json(string json, HttpStatusCode stato = HttpStatusCode.OK) =>
        new(stato) { Content = new StringContent(json, Encoding.UTF8, "application/json") };
}

/// <summary>Un NAS che non risponde mai (per i tempi brevi).</summary>
public sealed class NasMuto : HttpMessageHandler
{
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        await Task.Delay(Timeout.Infinite, cancellationToken);
        return new HttpResponseMessage(HttpStatusCode.OK);
    }
}

public static class Dati
{
    /// <summary>Un JPEG piccolo valido (8x8 grigio), per i lavori finti.</summary>
    public static readonly byte[] JpegMinimo = Convert.FromBase64String(
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwAoooqyD//Z");

    public static Lavoro LavoroFinto(string id = "l-1") => new()
    {
        Id = id,
        ImmagineJpegBase64 = Convert.ToBase64String(JpegMinimo),
        Contesto = "Camera, sul divano, 15:41.",
        Domande =
        {
            new DomandaLavoro { Id = "in_mano", Domanda = "Cosa tiene in mano la persona?", Opzioni = { "telefono", "tablet", "libro", "quaderno", "controller", "niente", "non_si_capisce" } },
            new DomandaLavoro { Id = "schermo_acceso", Domanda = "C'è uno schermo acceso davanti alla persona?", Opzioni = { "si", "no", "non_si_capisce" } },
        },
        Scade = "2099-01-01T00:00:00+01:00",
    };

    /// <summary>Una risposta di /v1/chat/completions con il contenuto dato.</summary>
    public static string RispostaChat(string contenuto) =>
        "{\"choices\":[{\"index\":0,\"message\":{\"role\":\"assistant\",\"content\":" +
        System.Text.Json.JsonSerializer.Serialize(contenuto) + "}}]}";

    /// <summary>Lunedì 9 novembre 2026 alle ore date (Italia, +01:00): giorno di scuola.</summary>
    public static DateTimeOffset Lunedi(int ora, int minuto = 0) => new(2026, 11, 9, ora, minuto, 0, TimeSpan.FromHours(1));
}
