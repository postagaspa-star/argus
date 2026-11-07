using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace Argus.Nucleo;

/// <summary>Trova llama-server.exe nella cartella più recente dei motori di LM Studio (senza toccare LM Studio).</summary>
public static class TrovaMotore
{
    /// <summary>La cartella di serie dei motori: %USERPROFILE%\.lmstudio\extensions\backends dell'utente.</summary>
    public static string CartellaDiSerie() =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".lmstudio", "extensions", "backends");

    /// <summary>
    /// Fra le cartelle date, quella con il nome "prefisso + versione" e la versione più alta
    /// ("llama.cpp-win-x86_64-avx2-2.43.0" batte "-2.41.0" e "-2.9.0"). Null se nessuna va bene.
    /// </summary>
    public static string? CartellaPiùRecente(IEnumerable<string> cartelle, string prefisso)
    {
        string? migliore = null;
        Version? versioneMigliore = null;
        foreach (var c in cartelle)
        {
            var nome = Path.GetFileName(c.TrimEnd('\\', '/'));
            if (!nome.StartsWith(prefisso, StringComparison.OrdinalIgnoreCase)) continue;
            var resto = nome[prefisso.Length..];
            if (!Version.TryParse(resto, out var v)) continue;
            if (versioneMigliore == null || v > versioneMigliore)
            {
                versioneMigliore = v;
                migliore = c;
            }
        }
        return migliore;
    }

    /// <summary>
    /// Il percorso di llama-server.exe: quello esplicito in config se c'è, altrimenti quello nella cartella più
    /// recente. Null (con il motivo) se non si trova.
    /// </summary>
    public static string? LlamaServer(ConfigMotore cfg, Func<string, IEnumerable<string>> sottocartelle, Func<string, bool> esiste, out string motivo)
    {
        if (!string.IsNullOrWhiteSpace(cfg.LlamaServer))
        {
            if (esiste(cfg.LlamaServer!)) { motivo = "ok"; return cfg.LlamaServer; }
            motivo = $"non trovo il motore indicato in config ({cfg.LlamaServer})";
            return null;
        }
        var radice = string.IsNullOrWhiteSpace(cfg.CartellaBackends) ? CartellaDiSerie() : cfg.CartellaBackends!;
        IEnumerable<string> elenco;
        try
        {
            elenco = sottocartelle(radice).ToList();
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or DirectoryNotFoundException)
        {
            motivo = $"non riesco a leggere la cartella dei motori ({radice})";
            return null;
        }
        var cartella = CartellaPiùRecente(elenco, cfg.PrefissoBackend);
        if (cartella == null)
        {
            motivo = $"nessun motore \"{cfg.PrefissoBackend}*\" in {radice}";
            return null;
        }
        var exe = Path.Combine(cartella, "llama-server.exe");
        if (!esiste(exe))
        {
            motivo = $"manca llama-server.exe in {cartella}";
            return null;
        }
        motivo = "ok";
        return exe;
    }

    /// <summary>Gli argomenti per llama-server: solo processore, solo 127.0.0.1, niente rete, niente pagina web.</summary>
    public static IReadOnlyList<string> Argomenti(ConfigMotore cfg, string? fileLog = null)
    {
        var a = new List<string>
        {
            "-m", cfg.Modello,
            "--mmproj", cfg.Mmproj,
            "--host", "127.0.0.1",
            "--port", cfg.Porta.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "-c", cfg.Contesto.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "-np", "1",
            "-ngl", "0",
            "-t", cfg.ThreadEffettivi().ToString(System.Globalization.CultureInfo.InvariantCulture),
            "--no-webui",
            "--offline",
            "--reasoning", "off",
            "-a", cfg.NomeModello,
        };
        if (!string.IsNullOrEmpty(fileLog))
        {
            a.Add("--log-file");
            a.Add(fileLog);
        }
        return a;
    }
}

/// <summary>Il risultato del modello su un lavoro: le risposte già controllate, o il motivo per cui non va.</summary>
public sealed record EsitoModello(bool Ok, Dictionary<string, string>? Risposte, string? Errore, IReadOnlyList<string> Sostituite)
{
    public static EsitoModello Fallito(string errore) => new(false, null, errore, Array.Empty<string>());
}

/// <summary>Come si chiede al modello e come si legge la sua risposta (regole 10, contratto GET /api/pc/lavori).</summary>
public static class DomandeModello
{
    public const string NonSiCapisce = "non_si_capisce";
    public const int MassimoDomande = 8;
    public const int MassimoOpzioni = 16;

    /// <summary>Il lavoro si può fare? (domande e opzioni sensate, immagine JPEG leggibile). Null se va bene.</summary>
    public static string? ProblemaLavoro(Lavoro l)
    {
        if (string.IsNullOrWhiteSpace(l.Id)) return "lavoro senza id";
        if (l.Domande == null || l.Domande.Count == 0) return "lavoro senza domande";
        if (l.Domande.Count > MassimoDomande) return "troppe domande";
        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var d in l.Domande)
        {
            if (string.IsNullOrWhiteSpace(d.Id) || !ids.Add(d.Id)) return "domanda senza id o ripetuta";
            if (d.Opzioni == null || d.Opzioni.Count == 0) return $"domanda {d.Id} senza opzioni";
            if (d.Opzioni.Count > MassimoOpzioni) return $"domanda {d.Id} con troppe opzioni";
            if (d.Opzioni.Any(string.IsNullOrWhiteSpace)) return $"domanda {d.Id} con un'opzione vuota";
        }
        var img = Immagine(l);
        if (img == null) return "immagine mancante o non in base64";
        if (img.Length < 4 || img[0] != 0xFF || img[1] != 0xD8) return "l'immagine non è un JPEG";
        return null;
    }

    public static byte[]? Immagine(Lavoro l)
    {
        if (string.IsNullOrWhiteSpace(l.ImmagineJpegBase64)) return null;
        var t = l.ImmagineJpegBase64.Trim();
        int virgola = t.IndexOf(',');
        if (t.StartsWith("data:", StringComparison.OrdinalIgnoreCase) && virgola > 0) t = t[(virgola + 1)..];
        try
        {
            return Convert.FromBase64String(t);
        }
        catch (FormatException)
        {
            return null;
        }
    }

    public const string Istruzioni =
        "Guardi un ritaglio di una foto presa da una telecamera dentro casa. Rispondi a ogni domanda scegliendo " +
        "una sola delle opzioni date, scritta esattamente com'è. Se non si vede bene o non sei sicuro, scegli " +
        "non_si_capisce (se c'è). Rispondi solo con un oggetto JSON, senza altro testo.";

    public static string TestoDomande(Lavoro l)
    {
        var sb = new StringBuilder();
        if (!string.IsNullOrWhiteSpace(l.Contesto)) sb.Append("Contesto: ").Append(l.Contesto!.Trim()).Append("\n\n");
        sb.Append("Domande:\n");
        foreach (var d in l.Domande)
        {
            sb.Append("- ").Append(d.Id).Append(": ").Append(d.Domanda.Trim()).Append('\n');
            sb.Append("  Opzioni: ").Append(string.Join(", ", d.Opzioni)).Append('\n');
        }
        sb.Append("\nRispondi con un oggetto JSON con le chiavi: ").Append(string.Join(", ", l.Domande.Select(d => d.Id))).Append('.');
        return sb.ToString();
    }

    /// <summary>Lo schema JSON che vincola la risposta: per ogni domanda una stringa tra le sue opzioni.</summary>
    public static JsonObject Schema(Lavoro l)
    {
        var proprieta = new JsonObject();
        foreach (var d in l.Domande)
        {
            var valori = new JsonArray();
            foreach (var o in d.Opzioni) valori.Add(o);
            proprieta[d.Id] = new JsonObject { ["type"] = "string", ["enum"] = valori };
        }
        var richieste = new JsonArray();
        foreach (var d in l.Domande) richieste.Add(d.Id);
        return new JsonObject
        {
            ["type"] = "object",
            ["properties"] = proprieta,
            ["required"] = richieste,
            ["additionalProperties"] = false,
        };
    }

    /// <summary>Il corpo di POST /v1/chat/completions: immagine + domande, risposta JSON vincolata alle opzioni.</summary>
    public static string CorpoRichiesta(Lavoro l, string nomeModello)
    {
        var img = Immagine(l) ?? Array.Empty<byte>();
        var corpo = new JsonObject
        {
            ["model"] = nomeModello,
            ["temperature"] = 0,
            ["max_tokens"] = 64 + 24 * l.Domande.Count,
            ["stream"] = false,
            ["messages"] = new JsonArray
            {
                new JsonObject { ["role"] = "system", ["content"] = Istruzioni },
                new JsonObject
                {
                    ["role"] = "user",
                    ["content"] = new JsonArray
                    {
                        new JsonObject
                        {
                            ["type"] = "image_url",
                            ["image_url"] = new JsonObject { ["url"] = "data:image/jpeg;base64," + Convert.ToBase64String(img) },
                        },
                        new JsonObject { ["type"] = "text", ["text"] = TestoDomande(l) },
                    },
                },
            },
            ["response_format"] = new JsonObject
            {
                ["type"] = "json_schema",
                ["json_schema"] = new JsonObject { ["name"] = "risposte", ["strict"] = true, ["schema"] = Schema(l) },
            },
            ["chat_template_kwargs"] = new JsonObject { ["enable_thinking"] = false },
        };
        return corpo.ToJsonString();
    }

    private static readonly Regex Pensiero = new(@"<think>.*?</think>", RegexOptions.Singleline | RegexOptions.Compiled);

    /// <summary>
    /// Legge la risposta di /v1/chat/completions e controlla ogni scelta: deve essere tra le opzioni della sua
    /// domanda. Una scelta mancante o fuori elenco diventa "non_si_capisce" se la domanda ce l'ha (nel dubbio,
    /// neutro); altrimenti il lavoro non si risponde.
    /// </summary>
    public static EsitoModello LeggiRisposta(string corpoRisposta, Lavoro l)
    {
        string? contenuto;
        try
        {
            var radice = JsonNode.Parse(corpoRisposta);
            var scelte = radice?["choices"] as JsonArray;
            if (scelte == null || scelte.Count == 0) return EsitoModello.Fallito("il motore non ha dato risposte");
            var messaggio = scelte[0]?["message"];
            contenuto = messaggio?["content"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(contenuto)) contenuto = messaggio?["reasoning_content"]?.GetValue<string>();
        }
        catch (Exception e) when (e is JsonException or InvalidOperationException or FormatException)
        {
            return EsitoModello.Fallito("risposta del motore non leggibile");
        }
        if (string.IsNullOrWhiteSpace(contenuto)) return EsitoModello.Fallito("il motore non ha scritto niente");
        return LeggiContenuto(contenuto, l);
    }

    public static EsitoModello LeggiContenuto(string contenuto, Lavoro l)
    {
        var t = Pensiero.Replace(contenuto, "").Trim();
        if (t.StartsWith("```", StringComparison.Ordinal))
        {
            int primo = t.IndexOf('\n');
            int ultimo = t.LastIndexOf("```", StringComparison.Ordinal);
            if (primo > 0 && ultimo > primo) t = t[(primo + 1)..ultimo].Trim();
        }
        int inizio = t.IndexOf('{');
        int fine = t.LastIndexOf('}');
        JsonObject? oggetto = null;
        if (inizio >= 0 && fine > inizio)
        {
            try
            {
                oggetto = JsonNode.Parse(t[inizio..(fine + 1)]) as JsonObject;
            }
            catch (JsonException)
            {
            }
        }
        if (oggetto == null) return EsitoModello.Fallito("il motore non ha risposto con un oggetto JSON");

        var risposte = new Dictionary<string, string>(StringComparer.Ordinal);
        var sostituite = new List<string>();
        foreach (var d in l.Domande)
        {
            string? scelta = null;
            if (oggetto.TryGetPropertyValue(d.Id, out var nodo) && nodo is JsonValue v && v.TryGetValue<string>(out var s))
                scelta = s.Trim();
            // Solo un'opzione dell'elenco, scritta uguale (si perdona solo maiuscole/minuscole).
            var giusta = scelta == null ? null : d.Opzioni.FirstOrDefault(o => string.Equals(o, scelta, StringComparison.OrdinalIgnoreCase));
            if (giusta != null)
            {
                risposte[d.Id] = giusta;
                continue;
            }
            var dubbio = d.Opzioni.FirstOrDefault(o => o == NonSiCapisce);
            if (dubbio == null) return EsitoModello.Fallito($"risposta fuori elenco per {d.Id}");
            risposte[d.Id] = dubbio;
            sostituite.Add(d.Id);
        }
        return new EsitoModello(true, risposte, null, sostituite);
    }
}
