using System.Globalization;

namespace Argus.Nucleo;

/// <summary>
/// I giorni di scuola (regole 2 e 13). Serve sul PC solo alla regola "senza NAS" (regole 12): il NAS ha il suo.
/// Anno 2026/27: il calendario del Veneto (DGR 712 del 07/07/2026). Per gli anni dopo, finché qualcuno non
/// aggiorna la tabella, una regola generica e prudente: lunedì-venerdì dal 10/09 all'08/06, meno le feste
/// nazionali, Natale (24/12-06/01) e Pasqua (da giovedì a martedì).
/// </summary>
public sealed class CalendarioScolastico
{
    private static readonly DateOnly Inizio2026 = new(2026, 9, 10);
    private static readonly DateOnly Fine2027 = new(2027, 6, 8);

    /// <summary>Regole 13: i giorni senza scuola dell'anno 2026/27, estremi compresi.</summary>
    private static readonly (DateOnly Dal, DateOnly Al)[] Vacanze2026 =
    {
        (new(2026, 10, 30), new(2026, 11, 2)),
        (new(2026, 12, 7), new(2026, 12, 8)),
        (new(2026, 12, 24), new(2027, 1, 6)),
        (new(2027, 2, 8), new(2027, 2, 13)),
        (new(2027, 3, 25), new(2027, 3, 30)),
        (new(2027, 4, 25), new(2027, 4, 25)),
        (new(2027, 4, 29), new(2027, 5, 1)),
        (new(2027, 5, 31), new(2027, 6, 2)),
    };

    private readonly bool sabatoScuola;
    private readonly (int Giorno, int Mese)? patrono;
    private readonly DateOnly? patronoData;

    public CalendarioScolastico(bool sabatoScuola = false, string? patrono = null)
    {
        this.sabatoScuola = sabatoScuola;
        (this.patrono, patronoData) = LeggiPatrono(patrono);
    }

    /// <summary>Il patrono: "GG/MM" (ogni anno) oppure "AAAA-MM-GG" (una data sola). Altro: ignorato.</summary>
    private static ((int, int)?, DateOnly?) LeggiPatrono(string? testo)
    {
        if (string.IsNullOrWhiteSpace(testo)) return (null, null);
        var t = testo.Trim();
        if (DateOnly.TryParseExact(t, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var d)) return (null, d);
        var parti = t.Split('/');
        if (parti.Length == 2 && int.TryParse(parti[0], out var g) && int.TryParse(parti[1], out var m)
            && m is >= 1 and <= 12 && g >= 1 && g <= DateTime.DaysInMonth(2028, m))
            return ((g, m), null);
        return (null, null);
    }

    public bool ÈGiornoDiScuola(DateOnly giorno)
    {
        var dow = giorno.DayOfWeek;
        if (dow == DayOfWeek.Sunday) return false;
        if (dow == DayOfWeek.Saturday && !sabatoScuola) return false;
        if (patrono is (int pg, int pm) && giorno.Day == pg && giorno.Month == pm) return false;
        if (patronoData is DateOnly pd && giorno == pd) return false;

        // L'anno 2026/27, dal calendario del Veneto.
        if (giorno >= new DateOnly(2026, 9, 1) && giorno < new DateOnly(2027, 9, 1))
        {
            if (giorno < Inizio2026 || giorno > Fine2027) return false;
            foreach (var (dal, al) in Vacanze2026)
            {
                if (giorno >= dal && giorno <= al) return false;
            }
            return true;
        }
        return GiornoGenerico(giorno);
    }

    /// <summary>Anni senza tabella: regola generica (da aggiornare quando esce il calendario vero).</summary>
    private static bool GiornoGenerico(DateOnly g)
    {
        int annoInizio = g.Month >= 9 ? g.Year : g.Year - 1;
        var inizio = new DateOnly(annoInizio, 9, 10);
        var fine = new DateOnly(annoInizio + 1, 6, 8);
        if (g < inizio || g > fine) return false;
        (int Giorno, int Mese)[] feste = { (1, 11), (8, 12), (25, 4), (1, 5), (2, 6) };
        foreach (var (fg, fm) in feste)
        {
            if (g.Day == fg && g.Month == fm) return false;
        }
        // Natale: 24/12 - 06/01.
        if ((g.Month == 12 && g.Day >= 24) || (g.Month == 1 && g.Day <= 6)) return false;
        // Pasqua: da giovedì a martedì.
        var pasqua = Pasqua(g.Year);
        if (g >= pasqua.AddDays(-3) && g <= pasqua.AddDays(2)) return false;
        return true;
    }

    /// <summary>La domenica di Pasqua (calendario gregoriano, algoritmo anonimo).</summary>
    public static DateOnly Pasqua(int anno)
    {
        int a = anno % 19, b = anno / 100, c = anno % 100, d = b / 4, e = b % 4;
        int f = (b + 8) / 25, g = (b - f + 1) / 3, h = (19 * a + b - d - g + 15) % 30;
        int i = c / 4, k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, m = (a + 11 * h + 22 * l) / 451;
        int mese = (h + l - 7 * m + 114) / 31, giorno = ((h + l - 7 * m + 114) % 31) + 1;
        return new DateOnly(anno, mese, giorno);
    }
}
