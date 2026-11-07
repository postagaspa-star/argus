namespace Argus.Nucleo;

/// <summary>
/// La combinazione che apre il terminale, da "tasto_terminale" in config.json (di serie Ctrl+Alt+T).
/// Si registra con RegisterHotKey: niente hook di tastiera.
/// </summary>
/// <param name="Modificatori">I modificatori per RegisterHotKey (MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN).</param>
/// <param name="TastoVirtuale">Il codice del tasto (virtual-key).</param>
/// <param name="Testo">Come si scrive per lo studente, per esempio "Ctrl+Alt+T".</param>
public sealed record TastoTerminale(uint Modificatori, uint TastoVirtuale, string Testo)
{
    public const string DiSerie = "Ctrl+Alt+T";

    public const uint ModAlt = 0x0001;
    public const uint ModCtrl = 0x0002;
    public const uint ModMaiusc = 0x0004;
    public const uint ModWin = 0x0008;

    public static TastoTerminale Predefinito { get; } = Leggi(DiSerie)!;

    /// <summary>
    /// "Ctrl+Alt+T", "ctrl + shift + spazio", "Alt+F9"... Null se non va bene: un solo tasto (lettera, cifra,
    /// F1-F24, Spazio) e almeno Ctrl, Alt o Win (con Maiusc da solo si mangerebbe una lettera mentre si scrive).
    /// </summary>
    public static TastoTerminale? Leggi(string? testo)
    {
        if (string.IsNullOrWhiteSpace(testo) || testo.Length > 60) return null;
        uint mod = 0;
        uint? vk = null;
        string? nomeTasto = null;
        foreach (var grezzo in testo.Split('+'))
        {
            var pezzo = grezzo.Trim().ToLowerInvariant();
            if (pezzo.Length == 0) return null;
            uint m = pezzo switch
            {
                "ctrl" or "control" or "ctl" => ModCtrl,
                "alt" => ModAlt,
                "shift" or "maiusc" or "maiuscolo" => ModMaiusc,
                "win" or "windows" => ModWin,
                _ => 0,
            };
            if (m != 0)
            {
                if ((mod & m) != 0) return null; // ripetuto
                mod |= m;
                continue;
            }
            if (vk != null) return null; // due tasti
            (vk, nomeTasto) = Tasto(pezzo);
            if (vk == null) return null;
        }
        if (vk == null || nomeTasto == null) return null;
        if ((mod & (ModCtrl | ModAlt | ModWin)) == 0) return null;

        var parti = new List<string>();
        if ((mod & ModCtrl) != 0) parti.Add("Ctrl");
        if ((mod & ModAlt) != 0) parti.Add("Alt");
        if ((mod & ModMaiusc) != 0) parti.Add("Maiusc");
        if ((mod & ModWin) != 0) parti.Add("Win");
        parti.Add(nomeTasto);
        return new TastoTerminale(mod, vk.Value, string.Join("+", parti));
    }

    private static (uint?, string?) Tasto(string p)
    {
        if (p is "spazio" or "space" or "barra spaziatrice") return (0x20, "Spazio");
        if (p.Length == 1 && p[0] is >= 'a' and <= 'z') return ((uint)char.ToUpperInvariant(p[0]), p.ToUpperInvariant());
        if (p.Length == 1 && p[0] is >= '0' and <= '9') return ((uint)p[0], p);
        if (p.Length is 2 or 3 && p[0] == 'f' && int.TryParse(p.AsSpan(1), out int n) && n is >= 1 and <= 24)
            return ((uint)(0x70 + n - 1), "F" + n);
        return (null, null);
    }
}
