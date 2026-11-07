using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace Argus.Nucleo;

/// <summary>
/// La risposta del NAS a una chiamata.
/// </summary>
/// <param name="Ok">Risposta 2xx letta bene.</param>
/// <param name="Dati">Il corpo letto (null per 204 o in caso di errore).</param>
/// <param name="Stato">Il codice HTTP (0 se il NAS non ha risposto).</param>
/// <param name="Errore">Una frase in italiano se qualcosa non va.</param>
/// <param name="Codice">Il "codice" dell'errore del NAS (contratto), o uno nostro: "rete", "timeout", "json", "indirizzo".</param>
/// <param name="Raggiunto">Il NAS ha risposto (anche con un errore).</param>
public sealed record RispostaNas<T>(bool Ok, T? Dati, int Stato, string? Errore, string? Codice, bool Raggiunto);

/// <summary>
/// Il client del contratto PC → NAS (sezione 3): token Bearer, tempi brevi, errori in italiano. Mai il token
/// nei log o negli errori. Il gestore HTTP si può passare da fuori (le prove usano un server finto).
/// </summary>
public sealed class ClientNas : IDisposable
{
    public const string NasNonRisponde = "Il NAS non risponde.";

    private readonly HttpClient http;
    private readonly Uri baseUrl;
    private readonly string? token;

    public TimeSpan TempoBreve { get; init; } = TimeSpan.FromSeconds(4);
    public TimeSpan TempoComando { get; init; } = TimeSpan.FromSeconds(10);
    public TimeSpan TempoFoto { get; init; } = TimeSpan.FromSeconds(90);
    public TimeSpan TempoVoce { get; init; } = TimeSpan.FromSeconds(10);

    public ClientNas(string indirizzo, string? token, HttpMessageHandler? gestore = null)
    {
        if (!Uri.TryCreate((indirizzo ?? "").Trim().TrimEnd('/') + "/", UriKind.Absolute, out var u) || (u.Scheme != "http" && u.Scheme != "https"))
            throw new ErroreConfig("L'indirizzo del NAS non è valido.");
        baseUrl = u;
        this.token = string.IsNullOrWhiteSpace(token) ? null : token.Trim();
        http = gestore == null
            ? new HttpClient(new SocketsHttpHandler { ConnectTimeout = TimeSpan.FromSeconds(3), PooledConnectionLifetime = TimeSpan.FromMinutes(5) })
            : new HttpClient(gestore, disposeHandler: false);
        http.Timeout = Timeout.InfiniteTimeSpan; // i tempi li decide ogni chiamata
        http.DefaultRequestHeaders.UserAgent.ParseAdd("Argus-PC/1.0");
    }

    public Uri Indirizzo => baseUrl;

    // ------------------------------------------------------------------ chiamate del contratto

    public Task<RispostaNas<SaluteNas>> SaluteAsync(CancellationToken ct = default) =>
        InviaAsync<SaluteNas>(HttpMethod.Get, "api/salute", null, TempoBreve, conToken: false, ct);

    public Task<RispostaNas<StatoNas>> StatoAsync(CancellationToken ct = default) =>
        InviaAsync<StatoNas>(HttpMethod.Get, "api/pc/stato", null, TempoBreve, conToken: true, ct);

    public async Task<RispostaNas<Liste>> ListeAsync(CancellationToken ct = default)
    {
        var r = await InviaAsync<Liste>(HttpMethod.Get, "api/pc/liste", null, TempoBreve, conToken: true, ct).ConfigureAwait(false);
        return r.Ok && r.Dati != null ? r with { Dati = r.Dati.Normalizzate() } : r;
    }

    public Task<RispostaNas<RispostaOk>> AttivitaAsync(IReadOnlyList<Campione> campioni, CancellationToken ct = default) =>
        InviaAsync<RispostaOk>(HttpMethod.Post, "api/pc/attivita", Json(new CorpoAttivita { Campioni = campioni.ToList() }), TempoBreve, true, ct);

    public Task<RispostaNas<RispostaComando>> ComandoAsync(string testo, CancellationToken ct = default) =>
        InviaAsync<RispostaComando>(HttpMethod.Post, "api/pc/comando", Json(new CorpoComando { Testo = testo }), TempoComando, true, ct,
            accettaCorpoDiErrore: true);

    /// <summary>
    /// POST /api/pc/evento. <paramref name="segretoSblocco"/> solo per <c>sblocco_emergenza</c> (intestazione
    /// X-Argus-Sblocco, contratto sezione 1): lo passano Argus.Sblocco e il guardiano, mai l'agente.
    /// </summary>
    public Task<RispostaNas<RispostaOk>> EventoAsync(string tipo, Dictionary<string, object?>? dettagli, DateTimeOffset ts,
        CancellationToken ct = default, string? segretoSblocco = null) =>
        InviaAsync<RispostaOk>(HttpMethod.Post, "api/pc/evento",
            Json(new Evento { Tipo = tipo, Dettagli = dettagli ?? new(), Ts = Tempo.Iso(ts) }), TempoBreve, true, ct,
            intestazioni: string.IsNullOrWhiteSpace(segretoSblocco) ? null : new() { [IntestazioneSblocco] = segretoSblocco.Trim() });

    public const string IntestazioneSblocco = "X-Argus-Sblocco";

    /// <summary>GET /api/pc/lavori: 204 = niente da fare (Ok con Dati null).</summary>
    public Task<RispostaNas<Lavoro>> LavoroAsync(CancellationToken ct = default) =>
        InviaAsync<Lavoro>(HttpMethod.Get, "api/pc/lavori", null, TimeSpan.FromSeconds(10), true, ct);

    public Task<RispostaNas<RispostaOk>> RispondiLavoroAsync(string id, RispostaLavoro risposta, CancellationToken ct = default) =>
        InviaAsync<RispostaOk>(HttpMethod.Post, "api/pc/lavori/" + Uri.EscapeDataString(id), Json(risposta), TimeSpan.FromSeconds(10), true, ct);

    /// <summary>POST /api/pc/foto (multipart): tipo, nome (per lb/qd), immagini (1-20, JPEG/PNG, max 8 MB l'una).</summary>
    public Task<RispostaNas<RispostaFoto>> FotoAsync(string tipo, string? nome, IReadOnlyList<ImmagineFoto> immagini, CancellationToken ct = default)
    {
        if (immagini.Count is < 1 or > 20)
            return Task.FromResult(new RispostaNas<RispostaFoto>(false, null, 0, "Servono da 1 a 20 foto.", "foto", false));
        if (immagini.Any(i => i.Dati.Length > 8 * 1024 * 1024))
            return Task.FromResult(new RispostaNas<RispostaFoto>(false, null, 0, "Una foto è più grande di 8 MB.", "foto", false));
        // Nomi dei campi tra virgolette (RFC 7578): li capiscono tutti i server, anche FastAPI.
        static StringContent Campo(string nome, string valore)
        {
            var c = new StringContent(valore, Encoding.UTF8);
            c.Headers.ContentType = null;
            c.Headers.ContentDisposition = new ContentDispositionHeaderValue("form-data") { Name = $"\"{nome}\"" };
            return c;
        }
        var corpo = new MultipartFormDataContent();
        corpo.Add(Campo("tipo", tipo));
        if (!string.IsNullOrWhiteSpace(nome)) corpo.Add(Campo("nome", nome));
        int n = 1;
        foreach (var i in immagini)
        {
            var parte = new ByteArrayContent(i.Dati);
            parte.Headers.ContentType = new MediaTypeHeaderValue(i.TipoMime);
            var estensione = i.TipoMime == "image/png" ? "png" : "jpg";
            parte.Headers.ContentDisposition = new ContentDispositionHeaderValue("form-data")
            {
                Name = "\"immagini\"",
                FileName = $"\"foto-{n++}.{estensione}\"",
            };
            corpo.Add(parte);
        }
        return InviaAsync<RispostaFoto>(HttpMethod.Post, "api/pc/foto", corpo, TempoFoto, true, ct, accettaCorpoDiErrore: true);
    }

    /// <summary>
    /// Scarica la voce di ripiego (contratto: di_voce.url, per esempio "/api/pc/voce/abc.wav"). Solo dallo
    /// stesso NAS: un indirizzo che porta altrove si rifiuta (il token non deve uscire).
    /// </summary>
    public async Task<RispostaNas<byte[]>> VoceAsync(string url, CancellationToken ct = default)
    {
        if (!Uri.TryCreate(baseUrl, url, out var assoluto)
            || assoluto.Scheme != baseUrl.Scheme || assoluto.Host != baseUrl.Host || assoluto.Port != baseUrl.Port)
            return new RispostaNas<byte[]>(false, null, 0, "Indirizzo della voce non valido.", "indirizzo", false);
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TempoVoce);
        try
        {
            using var richiesta = new HttpRequestMessage(HttpMethod.Get, assoluto);
            if (token != null) richiesta.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            using var risposta = await http.SendAsync(richiesta, cts.Token).ConfigureAwait(false);
            var dati = await risposta.Content.ReadAsByteArrayAsync(cts.Token).ConfigureAwait(false);
            if (!risposta.IsSuccessStatusCode)
                return new RispostaNas<byte[]>(false, null, (int)risposta.StatusCode, $"Il NAS non ha dato la voce ({(int)risposta.StatusCode}).", null, true);
            return new RispostaNas<byte[]>(true, dati, (int)risposta.StatusCode, null, null, true);
        }
        catch (Exception e) when (e is HttpRequestException or OperationCanceledException or IOException)
        {
            return Muto<byte[]>(ct.IsCancellationRequested ? "annullato" : (e is OperationCanceledException ? "timeout" : "rete"));
        }
    }

    // ------------------------------------------------------------------ il resto

    private static StringContent Json<T>(T corpo) =>
        new(JsonSerializer.Serialize(corpo, JsonArgus.Opzioni), Encoding.UTF8, "application/json");

    private static RispostaNas<T> Muto<T>(string codice) => new(false, default, 0, NasNonRisponde, codice, false);

    private async Task<RispostaNas<T>> InviaAsync<T>(HttpMethod metodo, string percorso, HttpContent? corpo, TimeSpan tempo,
        bool conToken, CancellationToken ct, bool accettaCorpoDiErrore = false, Dictionary<string, string>? intestazioni = null)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(tempo);
        try
        {
            using var richiesta = new HttpRequestMessage(metodo, new Uri(baseUrl, percorso)) { Content = corpo };
            if (conToken && token != null) richiesta.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            richiesta.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
            if (intestazioni != null)
                foreach (var (nome, valore) in intestazioni) richiesta.Headers.TryAddWithoutValidation(nome, valore);
            using var risposta = await http.SendAsync(richiesta, cts.Token).ConfigureAwait(false);
            int stato = (int)risposta.StatusCode;
            var testo = await risposta.Content.ReadAsStringAsync(cts.Token).ConfigureAwait(false);

            if (risposta.StatusCode == HttpStatusCode.NoContent)
                return new RispostaNas<T>(true, default, stato, null, null, true);

            if (risposta.IsSuccessStatusCode)
            {
                if (string.IsNullOrWhiteSpace(testo)) return new RispostaNas<T>(true, default, stato, null, null, true);
                try
                {
                    var dati = JsonSerializer.Deserialize<T>(testo, JsonArgus.Opzioni);
                    return new RispostaNas<T>(true, dati, stato, null, null, true);
                }
                catch (JsonException)
                {
                    return new RispostaNas<T>(false, default, stato, "Il NAS ha mandato una risposta che non capisco.", "json", true);
                }
            }

            // Errore: {"errore": "...", "codice": "..."} (contratto, sezione 1).
            ErroreNas? errore = null;
            T? datiErrore = default;
            try
            {
                errore = JsonSerializer.Deserialize<ErroreNas>(testo, JsonArgus.Opzioni);
                // Per i comandi un testo non capito può arrivare con ok:false e "risposta": la si tiene.
                if (accettaCorpoDiErrore) datiErrore = JsonSerializer.Deserialize<T>(testo, JsonArgus.Opzioni);
            }
            catch (JsonException)
            {
            }
            var frase = !string.IsNullOrWhiteSpace(errore?.Errore)
                ? errore!.Errore!.Trim()
                : stato == 401
                    ? "Il NAS non riconosce questo PC (token sbagliato)."
                    : stato == 403
                        ? "Il NAS non accetta lo sblocco (segreto dello sblocco sbagliato o mancante)."
                        : $"Il NAS ha risposto con un errore ({stato}).";
            var codice = errore?.Codice ?? (stato == 401 ? "token" : stato == 403 ? "sblocco" : null);
            return new RispostaNas<T>(false, datiErrore, stato, frase, codice, true);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            return Muto<T>("timeout");
        }
        catch (OperationCanceledException)
        {
            return Muto<T>("annullato");
        }
        catch (Exception e) when (e is HttpRequestException or IOException)
        {
            return Muto<T>("rete");
        }
    }

    public void Dispose() => http.Dispose();
}
