#Requires -Version 5.1
<#
.SYNOPSIS
    Installa Argus su questo PC (o lo aggiorna).

.DESCRIPTION
    Da lanciare in Windows PowerShell COME AMMINISTRATORE, dalla cartella del pacchetto:

        .\installa.ps1 -IndirizzoNas 192.168.1.10 -UtenteControllato nomeutente

    Cosa fa, in ordine:
      0. controlla tutto prima di cambiare qualcosa; alla prima installazione genera il segreto dello
         sblocco (32 byte casuali, mai mostrato) e lo registra sul NAS: se il NAS non risponde si ferma qui;
      1. ferma il guardiano e l'agente se c'erano (aggiornamento);
      2. copia il programma in C:\Program Files\Argus;
      3. prepara C:\ProgramData\Argus e la cartella del modello (SYSTEM e Administrators: tutto;
         Users: solo lettura);
      4. scrive config.json (leggibile solo da SYSTEM e Administrators) con indirizzo del NAS, token,
         segreto dello sblocco, utente controllato, tasto del terminale, percorsi del modello e percorsi fidati;
      5. scarica il modello per le foto dubbie (Qwen3.5-9B, circa 6,5 GB) e controlla l'impronta sha256;
      6. registra il servizio "ArgusGuardiano" (avvio automatico, si riavvia se cade) e lo avvia;
      7. mette nel menu Start "Argus - terminale" e "Argus - sblocco d'emergenza".

.PARAMETER IndirizzoNas
    Indirizzo del NAS: "192.168.1.10", "192.168.1.10:8700" o "http://192.168.1.10:8700".
    Senza porta si usa la 8700.

.PARAMETER Token
    Il token del PC (sul NAS in /data/token-pc.txt). Se manca, lo chiede senza mostrarlo.

.PARAMETER UtenteControllato
    Il nome dell'account Windows dello studente (quello che si vede in C:\Users\<nome>).

.PARAMETER SabatoScuola
    Da mettere se il sabato c'è scuola.

.PARAMETER Patrono
    Il giorno del santo patrono senza scuola, come "GG/MM" (esempio 15/06).

.PARAMETER SenzaModello
    Non scarica il modello (si può rilanciare dopo senza questa opzione: scarica solo quello che manca).

.PARAMETER SenzaMotore
    Il PC non fa mai girare il modello: le foto dubbie le guarda solo il NAS.

.PARAMETER CartellaModelli
    Dove mettere il modello (circa 6,5 GB). Di serie: D:\Argus\modelli se D: è un disco fisso con almeno
    8 GB liberi, altrimenti C:\ProgramData\Argus\modelli. In un aggiornamento, se il modello c'è già nella
    cartella dell'installazione di prima, resta lì.

.PARAMETER TastoTerminale
    La combinazione che apre il terminale (di serie "Ctrl+Alt+T"). Esempi: "Ctrl+Alt+A", "Ctrl+Maiusc+Spazio".

.PARAMETER PercorsiFidati
    Programmi fatti in casa, senza firma digitale, che stanno in cartelle dove lo studente può scrivere
    (per esempio C:\Users\studente\AppData\Local\Programs\App\App.exe): percorsi completi, separati da virgole.
    Valgono solo con quel percorso esatto. Senza questa opzione restano quelli dell'installazione di prima;
    con -PercorsiFidati @() si tolgono tutti.

.PARAMETER NuovoSegretoSblocco
    Solo per una reinstallazione voluta: genera un segreto dello sblocco nuovo anche se config.json ne ha già
    uno e lo registra sul NAS. Prima chi gestisce il NAS deve cancellare /data/token-sblocco.txt, altrimenti
    il NAS risponde che ce n'è già uno e l'installazione si ferma.

.PARAMETER CartellaProgramma
    Dove sono i file del programma (di serie: la cartella "programma" accanto a questo script).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$IndirizzoNas,
    [string]$Token,
    [Parameter(Mandatory = $true)][string]$UtenteControllato,
    [switch]$SabatoScuola,
    [string]$Patrono,
    [switch]$SenzaModello,
    [switch]$SenzaMotore,
    [string]$CartellaModelli,
    [string]$TastoTerminale = 'Ctrl+Alt+T',
    [string[]]$PercorsiFidati,
    [switch]$NuovoSegretoSblocco,
    [string]$CartellaProgramma
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- costanti

$NomeServizio   = 'ArgusGuardiano'
$Destinazione   = Join-Path $env:ProgramFiles 'Argus'
$Dati           = Join-Path $env:ProgramData 'Argus'
$FileConfig     = Join-Path $Dati 'config.json'
$MenuStart      = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Argus'
$PortaNas       = 8700

# SID fissi: funzionano con Windows in qualsiasi lingua ("Users" in italiano è "Utenti").
$SidSystem = '*S-1-5-18'
$SidAdmin  = '*S-1-5-32-544'
$SidUsers  = '*S-1-5-32-545'

# Il modello per le foto dubbie (lmstudio-community/Qwen3.5-9B-GGUF), con dimensione e sha256 presi da
# Hugging Face (?blobs=true): se il file scaricato non torna, si butta.
$Modelli = @(
    @{ Nome = 'Qwen3.5-9B-Q4_K_M.gguf';      Byte = 5627044256; Sha256 = 'cd76ec205963b3b33350093e6904d9de16c4e666fd104e1f632d25c7f15f2a13' },
    @{ Nome = 'mmproj-Qwen3.5-9B-BF16.gguf'; Byte = 921704480;  Sha256 = '330d17547bfdbcd0e7a0cb3f4b06b4ceeac0aaa1e449122d9d66ef957aeb74b3' }
)
$UrlModelli = 'https://huggingface.co/lmstudio-community/Qwen3.5-9B-GGUF/resolve/main/'

# ---------------------------------------------------------------- aiuti

function Passo([string]$testo) { Write-Host ''; Write-Host "== $testo" -ForegroundColor Cyan }
function Ok([string]$testo) { Write-Host "   $testo" -ForegroundColor Green }
function Nota([string]$testo) { Write-Host "   $testo" }
function Attenzione([string]$testo) { Write-Host "   ATTENZIONE: $testo" -ForegroundColor Yellow }
function Ferma([string]$testo) {
    Write-Host ''
    Write-Host "Installazione fermata: $testo" -ForegroundColor Red
    exit 1
}

function Esegui([string]$programma, [string[]]$argomenti) {
    # In Windows PowerShell 5.1 una riga su stderr con 'Stop' diventerebbe un errore anche se il programma
    # riesce: qui conta solo il codice di uscita.
    $prima = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $uscita = & $programma @argomenti 2>&1 | Out-String } finally { $ErrorActionPreference = $prima }
    if ($LASTEXITCODE -ne 0) { throw "$programma $($argomenti -join ' ') -> codice $LASTEXITCODE`n$uscita" }
}

function ScriviUtf8([string]$percorso, [string]$testo) {
    [System.IO.File]::WriteAllText($percorso, $testo, (New-Object System.Text.UTF8Encoding $false))
}

function GbDa([double]$byte) { [math]::Round($byte / 1GB, 1) }

# Una proprietà di un oggetto letto da JSON, o $null se non c'è (con StrictMode leggerla direttamente darebbe errore).
function Proprieta($oggetto, [string]$nome) {
    if ($null -ne $oggetto -and $oggetto.PSObject.Properties[$nome]) { return $oggetto.PSObject.Properties[$nome].Value }
    return $null
}

# Proprietario Administrators (chi avesse creato la cartella prima non tiene il diritto di cambiarne i permessi),
# niente permessi ereditati (in ProgramData e nella radice di D: gli utenti possono creare e modificare file),
# SYSTEM e Administrators controllo completo, Users solo lettura; i file dentro ereditano questi permessi.
# config.json no: ha i suoi permessi (solo SYSTEM e Administrators) e non passa mai da "Users: lettura".
function Proteggi([string]$cartella) {
    Esegui 'icacls.exe' @($cartella, '/setowner', $SidAdmin, '/T', '/C', '/Q')
    Esegui 'icacls.exe' @($cartella, '/inheritance:r', '/grant:r', "${SidSystem}:(OI)(CI)F", "${SidAdmin}:(OI)(CI)F", "${SidUsers}:(OI)(CI)RX", '/Q')
    Get-ChildItem -LiteralPath $cartella -Force | Where-Object { $_.Name -ne 'config.json' } | ForEach-Object {
        Esegui 'icacls.exe' @($_.FullName, '/reset', '/T', '/C', '/Q')
    }
}

#region Config protetta e segreto dello sblocco
# config.json nasce già con i suoi permessi (solo SYSTEM e Administrators): non c'è mai un momento in cui lo studente
# può leggerlo. Quello vecchio si cancella prima, così chi lo avesse aperto resta con il file vecchio; se qualcuno lo
# rimette nel frattempo (CreateNew fallisce) ci si ferma invece di scrivere in un file suo.
function ScriviConfig([string]$testo) {
    $permessi = New-Object System.Security.AccessControl.FileSecurity
    $permessi.SetAccessRuleProtection($true, $false)
    foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
        $chi = New-Object System.Security.Principal.SecurityIdentifier($sid)
        $permessi.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($chi,
            [System.Security.AccessControl.FileSystemRights]::FullControl, [System.Security.AccessControl.AccessControlType]::Allow)))
    }
    $byte = (New-Object System.Text.UTF8Encoding $false).GetBytes($testo)
    try {
        if (Test-Path -LiteralPath $FileConfig) { Remove-Item -LiteralPath $FileConfig -Force }
        $flusso = New-Object System.IO.FileStream($FileConfig, [System.IO.FileMode]::CreateNew,
            [System.Security.AccessControl.FileSystemRights]::Write, [System.IO.FileShare]::None, 4096,
            [System.IO.FileOptions]::WriteThrough, $permessi)
    }
    catch {
        Ferma "non riesco a scrivere $FileConfig ($($_.Exception.Message)). È aperto da un altro programma? Riavvia il PC e rilancia."
    }
    try { $flusso.Write($byte, 0, $byte.Length) } finally { $flusso.Dispose() }
}

# Registra il segreto dello sblocco sul NAS (POST /api/pc/registra-sblocco con il token del PC). Il segreto viaggia
# solo nel corpo della richiesta: mai sullo schermo, mai nei registri, mai nell'indirizzo. Torna 'ok',
# 'gia_registrato' (409), 'token' (401), 'nessuna_risposta' o 'errore <codice>'.
function RegistraSegreto([string]$segreto) {
    $richiesta = @{
        UseBasicParsing = $true
        TimeoutSec      = 15
        Method          = 'Post'
        Uri             = "$indirizzo/api/pc/registra-sblocco"
        Headers         = @{ Authorization = "Bearer $Token" }
        ContentType     = 'application/json'
        Body            = '{"segreto": "' + $segreto + '"}'
    }
    try {
        $null = Invoke-WebRequest @richiesta
        return 'ok'
    }
    catch {
        $e = $_.Exception
        if ($e -is [System.Net.WebException] -and $e.Response) {
            $codice = [int]$e.Response.StatusCode
            if ($codice -eq 409) { return 'gia_registrato' }
            if ($codice -eq 401) { return 'token' }
            return "errore $codice"
        }
        return 'nessuna_risposta'
    }
}
#endregion

# ---------------------------------------------------------------- 0. controlli

Passo 'Controlli'

$io = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $io.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Ferma 'serve PowerShell aperto come amministratore (tasto destro su Windows PowerShell > Esegui come amministratore).'
}
if ([Environment]::Is64BitOperatingSystem -eq $false -or [IntPtr]::Size -ne 8) {
    Ferma 'serve Windows a 64 bit e Windows PowerShell a 64 bit (non quello "(x86)").'
}

# La configurazione dell'installazione di prima (aggiornamento), se c'è.
$vecchiaConfig = $null
if (Test-Path -LiteralPath $FileConfig) {
    try { $vecchiaConfig = Get-Content -LiteralPath $FileConfig -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
}

if (-not $CartellaProgramma) { $CartellaProgramma = Join-Path $PSScriptRoot 'programma' }
foreach ($f in @('Argus.Guardiano.exe', 'Argus.Agente.exe', 'Argus.Sblocco.exe', 'ui\terminale.html')) {
    if (-not (Test-Path -LiteralPath (Join-Path $CartellaProgramma $f))) {
        Ferma "nella cartella del programma ($CartellaProgramma) manca $f. Usa la cartella preparata da crea-pacchetto.ps1."
    }
}
Ok "programma trovato in $CartellaProgramma"

# Indirizzo del NAS: si accetta anche senza http:// e senza porta.
$indirizzo = $IndirizzoNas.Trim().TrimEnd('/')
if ($indirizzo -notmatch '^[a-zA-Z]+://') { $indirizzo = "http://$indirizzo" }
try { $uri = [Uri]$indirizzo } catch { Ferma "l'indirizzo del NAS '$IndirizzoNas' non è valido." }
if ($uri.Scheme -ne 'http' -and $uri.Scheme -ne 'https') { Ferma "l'indirizzo del NAS deve cominciare con http:// o https://." }
if ($IndirizzoNas -notmatch ':\d+(/|$)') { $indirizzo = "$($uri.Scheme)://$($uri.Host):$PortaNas" }
else { $indirizzo = "$($uri.Scheme)://$($uri.Authority)" }
Ok "NAS: $indirizzo"

# Il token: mai sullo schermo.
if (-not $Token) {
    $sicuro = Read-Host -AsSecureString 'Token del PC (sul NAS in /data/token-pc.txt; non si vede mentre lo scrivi)'
    $p = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sicuro)
    try { $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($p) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p) }
}
$Token = $Token.Trim()
if (-not $Token) { Ferma 'manca il token del PC.' }
if ($Token -notmatch '^[0-9a-fA-F]{64}$') { Attenzione 'il token non sembra quello del NAS (di solito sono 64 caratteri 0-9 a-f). Vado avanti lo stesso.' }

# Il NAS risponde? Il token è giusto?
$nasRisponde = $false
try {
    $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 -Uri "$indirizzo/api/salute"
    $nasRisponde = $true
    Ok 'il NAS risponde'
}
catch {
    Attenzione "il NAS non risponde adesso ($($_.Exception.Message)). Vado avanti: Argus userà la regola 'senza NAS' finché non torna."
}
if ($nasRisponde) {
    $codice = 0
    try {
        $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 -Uri "$indirizzo/api/pc/stato" -Headers @{ Authorization = "Bearer $Token" }
        Ok 'il NAS riconosce il token'
    }
    catch {
        $e = $_.Exception
        if ($e -is [System.Net.WebException] -and $e.Response) { $codice = [int]$e.Response.StatusCode }
        if ($codice -ne 401) { Attenzione "il NAS ha risposto con un errore al controllo del token ($($e.Message)). Vado avanti." }
    }
    if ($codice -eq 401) { Ferma 'il NAS non riconosce questo token: ricopialo da /data/token-pc.txt sul NAS.' }
}

# Utente controllato: deve esistere e non dovrebbe essere amministratore.
$utente = $UtenteControllato.Trim()
if ($utente -match '[\\@]') { Ferma 'scrivi solo il nome dell''utente, senza dominio e senza @ (esempio: studente).' }
$locali = @()
try { $locali = @(Get-LocalUser | ForEach-Object { $_.Name }) } catch { }
if ($locali.Count -gt 0 -and -not ($locali -contains $utente)) {
    Attenzione "non trovo l'utente '$utente' tra gli account di questo PC. Utenti trovati: $($locali -join ', ')."
}
try {
    $admin = @(Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction Stop | Where-Object { ($_.Name -split '\\')[-1] -eq $utente })
    if ($admin.Count -gt 0) { Attenzione "'$utente' è amministratore di questo PC: potrebbe fermare Argus. Meglio un account standard." }
}
catch { }

if ($Patrono -and $Patrono -notmatch '^\d{1,2}/\d{1,2}$') { Ferma 'il patrono va scritto come GG/MM (esempio 15/06).' }

# Tasto del terminale: lo controlla anche l'agente (se non va bene usa Ctrl+Alt+T); qui solo la forma.
$TastoTerminale = $TastoTerminale.Trim()
if ($TastoTerminale -notmatch '^((ctrl|control|alt|shift|maiusc|win)\s*\+\s*){1,4}([a-z0-9]|f\d{1,2}|spazio|space)$' -or
    $TastoTerminale -notmatch 'ctrl|control|alt|win') {
    Ferma "il tasto del terminale '$TastoTerminale' non va bene: scrivilo come Ctrl+Alt+T (almeno Ctrl, Alt o Win, più una lettera, una cifra, F1-F24 o Spazio)."
}
Ok "tasto del terminale: $TastoTerminale"

# Cartella del modello: quella chiesta; altrimenti quella di prima se il modello c'è già (non si riscarica);
# altrimenti D:\Argus\modelli se D: è un disco fisso con almeno 8 GB liberi; altrimenti C:\ProgramData\Argus\modelli.
function ModelloGiaIn([string]$cartella) {
    foreach ($m in $Modelli) {
        $f = Join-Path $cartella $m.Nome
        if (-not (Test-Path -LiteralPath $f) -or (Get-Item -LiteralPath $f).Length -ne $m.Byte) { return $false }
    }
    return $true
}
if ($CartellaModelli) {
    if (-not [System.IO.Path]::IsPathRooted($CartellaModelli) -or $CartellaModelli.StartsWith('\\') -or $CartellaModelli -notmatch '^[a-zA-Z]:\\') {
        Ferma 'la cartella del modello deve essere un percorso completo su un disco di questo PC (esempio D:\Argus\modelli).'
    }
    $CartellaModelli = [System.IO.Path]::GetFullPath($CartellaModelli).TrimEnd('\')
    $unita = New-Object System.IO.DriveInfo($CartellaModelli.Substring(0, 1))
    if (-not $unita.IsReady -or $unita.DriveType -ne [System.IO.DriveType]::Fixed) {
        Ferma "il disco $($unita.Name) non è un disco fisso pronto: il modello va su un disco interno."
    }
    if ($CartellaModelli.Length -le 3) { Ferma 'la cartella del modello non può essere la radice di un disco: usa per esempio D:\Argus\modelli.' }
    # I permessi della cartella si cambiano: deve essere nuova, vuota o contenere solo il modello.
    if (Test-Path -LiteralPath $CartellaModelli) {
        $altro = @(Get-ChildItem -LiteralPath $CartellaModelli -Force | Where-Object { $_.PSIsContainer -or ($_.Name -notlike '*.gguf' -and $_.Name -notlike '*.gguf.part') })
        if ($altro.Count -gt 0) { Ferma "la cartella $CartellaModelli contiene altri file: scegline una nuova o vuota (esempio D:\Argus\modelli)." }
    }
}
else {
    $precedente = $null
    $vecchioModello = Proprieta (Proprieta $vecchiaConfig 'motore') 'modello'
    if ($vecchioModello) { try { $precedente = Split-Path -Parent $vecchioModello } catch { } }
    if ($precedente -and (ModelloGiaIn $precedente)) {
        $CartellaModelli = $precedente
        Nota 'il modello c''è già nella cartella dell''installazione di prima: resta lì.'
    }
    else {
        $CartellaModelli = Join-Path $Dati 'modelli'
        try {
            $d = New-Object System.IO.DriveInfo('D')
            if ($d.IsReady -and $d.DriveType -eq [System.IO.DriveType]::Fixed -and $d.AvailableFreeSpace -ge 8GB) { $CartellaModelli = 'D:\Argus\modelli' }
        }
        catch { }
    }
}
Ok "cartella del modello: $CartellaModelli"
$FileModello = Join-Path $CartellaModelli $Modelli[0].Nome
$FileMmproj  = Join-Path $CartellaModelli $Modelli[1].Nome

# WebView2 (il terminale). Su Windows 11 c'è sempre.
$chiaviWv2 = @(
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
    'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
)
$wv2 = $false
foreach ($k in $chiaviWv2) { if (Test-Path $k) { $wv2 = $true } }
if (-not $wv2) { Attenzione 'non trovo "Microsoft Edge WebView2 Runtime": senza, il terminale non si apre. Installalo da microsoft.com.' }

# Percorsi fidati: programmi fatti in casa, senza firma, in cartelle dove lo studente può scrivere (per tutti gli
# altri bastano la cartella protetta o la firma). Valgono solo con il percorso completo esatto.
if ($PSBoundParameters.ContainsKey('PercorsiFidati')) {
    $fidati = @()
    foreach ($f in @($PercorsiFidati | Where-Object { $_ -and $_.Trim() })) {
        $f = $f.Trim().Trim('"')
        if ($f -notmatch '^[a-zA-Z]:\\' -or $f -notmatch '\.exe$') {
            Ferma "il percorso fidato '$f' va scritto completo e deve finire con .exe (esempio C:\Users\studente\AppData\Local\Programs\App\App.exe)."
        }
        $f = [System.IO.Path]::GetFullPath($f)
        if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { Attenzione "il programma $f non c'è (adesso): lo scrivo lo stesso." }
        $fidati += $f
    }
}
else {
    $fidati = @(Proprieta $vecchiaConfig 'percorsi_fidati' | Where-Object { $_ })
}
if ($fidati.Count -gt 0) {
    Ok "percorsi fidati: $($fidati.Count)"
    foreach ($f in $fidati) { Nota "  $f" }
    Nota 'chi può scrivere in quelle cartelle può sostituire il programma: se puoi, installali in C:\Program Files.'
}

#region Segreto dello sblocco
# Il segreto dello sblocco (contratto, sezione 1) lo genera questo script, che gira come amministratore: così non
# passa mai dalle mani dello studente. Il NAS lo accetta una volta sola. Mai sullo schermo né nei registri.
# Aggiornamento con il segreto già in config.json: resta quello e non si registra di nuovo.
$SegretoSblocco = Proprieta $vecchiaConfig 'segreto_sblocco'
if ($SegretoSblocco -and $SegretoSblocco -notmatch '^[0-9a-fA-F]{64}$') { $SegretoSblocco = $null }
if ($SegretoSblocco -and -not $NuovoSegretoSblocco) {
    Ok 'segreto dello sblocco: c''è già in config.json, resta quello'
}
else {
    if (-not $nasRisponde) {
        Ferma 'il NAS non risponde e devo registrarci il segreto dello sblocco. Non ho cambiato niente: controlla che il NAS sia acceso e raggiungibile, poi rilancia.'
    }
    $byte = New-Object byte[] 32
    $generatore = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generatore.GetBytes($byte) } finally { $generatore.Dispose() }
    $nuovoSegreto = -join ($byte | ForEach-Object { $_.ToString('x2') })
    $byte = $null
    $esito = RegistraSegreto $nuovoSegreto
    if ($esito -eq 'gia_registrato') { Ferma 'Sul NAS c''è già un segreto di sblocco: va azzerato da chi gestisce il NAS, poi rilancia l''installazione.' }
    if ($esito -eq 'token') { Ferma 'il NAS non riconosce questo token: ricopialo da /data/token-pc.txt sul NAS. Non ho cambiato niente.' }
    if ($esito -eq 'nessuna_risposta') { Ferma 'il NAS non ha risposto alla registrazione del segreto dello sblocco. Non ho cambiato niente: rilancia quando il NAS risponde.' }
    if ($esito -ne 'ok') { Ferma "il NAS non ha accettato il segreto dello sblocco ($esito). Non ho cambiato niente." }
    $SegretoSblocco = $nuovoSegreto
    $nuovoSegreto = $null
    # Subito in config.json: se l'installazione si fermasse più avanti, rilanciandola il segreto c'è già e non si
    # registra di nuovo (il NAS risponderebbe che ce n'è già uno).
    New-Item -ItemType Directory -Path $Dati -Force | Out-Null
    Proteggi $Dati
    $parziale = $vecchiaConfig
    if ($null -eq $parziale) { $parziale = New-Object PSObject }
    $parziale | Add-Member -NotePropertyName 'segreto_sblocco' -NotePropertyValue $SegretoSblocco -Force
    ScriviConfig ($parziale | ConvertTo-Json -Depth 6)
    $parziale = $null
    Ok 'segreto dello sblocco generato, registrato sul NAS e scritto in config.json (non si mostra)'
}
#endregion

# ---------------------------------------------------------------- 1. fermare la versione vecchia

Passo 'Fermo la versione già installata (se c''è)'
$servizio = Get-Service -Name $NomeServizio -ErrorAction SilentlyContinue
if ($servizio) {
    if ($servizio.Status -ne 'Stopped') {
        Stop-Service -Name $NomeServizio -Force
        $servizio.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
    }
    Ok 'guardiano fermato'
}
# Solo i programmi di Argus (l'agente spegne da sé il suo motore quando si chiude).
foreach ($nome in @('Argus.Agente', 'Argus.Sblocco')) {
    Get-Process -Name $nome -ErrorAction SilentlyContinue | ForEach-Object {
        try { $_.Kill(); $_.WaitForExit(5000) | Out-Null; Ok "chiuso $nome (pid $($_.Id))" } catch { Attenzione "non riesco a chiudere $nome (pid $($_.Id))" }
    }
}

# ---------------------------------------------------------------- 2. programma

Passo "Copio il programma in $Destinazione"
# I file appena chiusi (agente, WebView2) possono restare bloccati per qualche secondo: tre tentativi.
for ($tentativo = 1; (Test-Path -LiteralPath $Destinazione); $tentativo++) {
    try { Remove-Item -LiteralPath $Destinazione -Recurse -Force }
    catch {
        if ($tentativo -ge 3) { Ferma "non riesco a togliere la versione vecchia in $Destinazione ($($_.Exception.Message)). Riavvia il PC e riprova." }
        Start-Sleep -Seconds 3
    }
}
New-Item -ItemType Directory -Path $Destinazione -Force | Out-Null
Copy-Item -Path (Join-Path $CartellaProgramma '*') -Destination $Destinazione -Recurse -Force
# Program Files eredita già i permessi giusti (Users: solo lettura ed esecuzione).
Ok 'copiato'

# ---------------------------------------------------------------- 3. dati

Passo "Preparo $Dati e la cartella del modello"
New-Item -ItemType Directory -Path $Dati -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Dati 'log') -Force | Out-Null
Proteggi $Dati
# Il config.json di prima (di una versione vecchia) solo per SYSTEM e Administrators: Proteggi non lo tocca.
if (Test-Path -LiteralPath $FileConfig) { Esegui 'icacls.exe' @($FileConfig, '/inheritance:r', '/grant:r', "${SidSystem}:F", "${SidAdmin}:F", '/Q') }
New-Item -ItemType Directory -Path $CartellaModelli -Force | Out-Null
$datiPieno = [System.IO.Path]::GetFullPath($Dati).TrimEnd('\') + '\'
if (-not ($CartellaModelli + '\').StartsWith($datiPieno, [StringComparison]::OrdinalIgnoreCase)) {
    # Fuori da ProgramData (per esempio D:\Argus\modelli): stessi permessi. Se la cartella sopra si chiama
    # "Argus" e non è la radice del disco (D:\Argus), si protegge lei, così nessuno può metterci altro accanto.
    $sopra = Split-Path -Parent $CartellaModelli
    $soloModelli = @(Get-ChildItem -LiteralPath $sopra -Force | Where-Object { $_.FullName.TrimEnd([char]92) -ine $CartellaModelli }).Count -eq 0
    if ((Split-Path -Leaf $sopra) -ieq 'Argus' -and $sopra.Length -gt 3 -and $soloModelli) { Proteggi $sopra } else { Proteggi $CartellaModelli }
}
Ok 'permessi: SYSTEM e Administrators tutto, Users solo lettura (anche sulla cartella del modello)'

# ---------------------------------------------------------------- 4. config.json

Passo 'Scrivo la configurazione'
$config = [ordered]@{
    nas_url            = $indirizzo
    token              = $Token
    segreto_sblocco    = $SegretoSblocco
    utente_controllato = $utente
    sabato_scuola      = [bool]$SabatoScuola
    tasto_terminale    = $TastoTerminale
}
if ($Patrono) { $config.patrono = $Patrono }
# I percorsi del modello vanno sempre in config.json: l'agente li legge da lì (il modello può stare su D:).
$config.motore = [ordered]@{ attivo = (-not $SenzaMotore); modello = $FileModello; mmproj = $FileMmproj }
$config.percorsi_fidati = @($fidati)
# Token e segreto dello sblocco non deve leggerli lo studente: solo SYSTEM e Administrators. Il guardiano passa
# all'agente la configurazione SENZA il segreto dello sblocco.
ScriviConfig ($config | ConvertTo-Json -Depth 4)
$Token = $null
$SegretoSblocco = $null
Ok "config.json scritto (leggibile solo da SYSTEM e Administrators)"

# ---------------------------------------------------------------- 5. modello

Passo 'Modello per le foto dubbie'
function ImprontaGiusta([string]$file, $m) {
    if (-not (Test-Path -LiteralPath $file)) { return $false }
    if ((Get-Item -LiteralPath $file).Length -ne $m.Byte) { return $false }
    Nota "controllo l'impronta di $($m.Nome) (qualche decina di secondi)..."
    return ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -eq $m.Sha256)
}

$modelloPronto = $true
if ($SenzaMotore) {
    Nota 'motore spento (-SenzaMotore): niente modello, le foto dubbie le guarda il NAS.'
    $modelloPronto = $false
}
elseif ($SenzaModello) {
    Nota 'salto il modello (-SenzaModello). Rilancia lo script senza questa opzione per scaricarlo.'
    $modelloPronto = $false
}
else {
    $mancanti = @()
    foreach ($m in $Modelli) {
        $file = Join-Path $CartellaModelli $m.Nome
        if (ImprontaGiusta $file $m) { Ok "$($m.Nome) c'è già ed è giusto" } else { $mancanti += $m }
    }
    if ($mancanti.Count -gt 0) {
        # Spazio: quello che manca (meno la parte già scaricata) più 1 GB di margine.
        [long]$serve = 1GB
        foreach ($m in $mancanti) {
            $parte = Join-Path $CartellaModelli ($m.Nome + '.part')
            [long]$giaScaricati = 0
            if (Test-Path -LiteralPath $parte) { $giaScaricati = (Get-Item -LiteralPath $parte).Length }
            $serve += [math]::Max([long]0, [long]($m.Byte - $giaScaricati))
        }
        $disco = Get-PSDrive -Name ($CartellaModelli.Substring(0, 1))
        if ($disco.Free -lt $serve) {
            Attenzione ("spazio libero insufficiente sul disco $($disco.Name): ($CartellaModelli): servono $(GbDa $serve) GB, liberi $(GbDa $disco.Free) GB. " +
                "Argus funziona lo stesso: le foto dubbie le guarda il NAS. Libera spazio (o scegli un altro disco con -CartellaModelli) e rilancia lo script.")
            $modelloPronto = $false
        }
        else {
            $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
            foreach ($m in $mancanti) {
                $file = Join-Path $CartellaModelli $m.Nome
                $parte = $file + '.part'
                $url = $UrlModelli + $m.Nome
                Nota "scarico $($m.Nome) ($(GbDa $m.Byte) GB): può volerci molto. Se si interrompe, rilancia: riprende da dove era."
                if (Test-Path -LiteralPath $curl) {
                    # curl scrive l'avanzamento su stderr: non è un errore.
                    $prima = $ErrorActionPreference
                    $ErrorActionPreference = 'Continue'
                    try { & $curl -L --fail --retry 5 --retry-delay 10 --connect-timeout 30 -C - -o $parte $url } finally { $ErrorActionPreference = $prima }
                    if ($LASTEXITCODE -ne 0) {
                        Attenzione "download di $($m.Nome) interrotto (codice $LASTEXITCODE). Rilancia lo script per riprendere."
                        $modelloPronto = $false
                        continue
                    }
                }
                else {
                    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                    (New-Object Net.WebClient).DownloadFile($url, $parte)
                }
                if (ImprontaGiusta $parte $m) {
                    Move-Item -LiteralPath $parte -Destination $file -Force
                    Ok "$($m.Nome) scaricato e controllato"
                }
                else {
                    Remove-Item -LiteralPath $parte -Force -ErrorAction SilentlyContinue
                    Attenzione "$($m.Nome) scaricato ma l'impronta non torna: l'ho buttato. Rilancia lo script."
                    $modelloPronto = $false
                }
            }
        }
    }
}
# I file del modello ereditano Users: lettura (l'agente gira come studente e li deve leggere).

# ---------------------------------------------------------------- 6. servizio

Passo 'Registro e avvio il guardiano'
$exeGuardiano = Join-Path $Destinazione 'Argus.Guardiano.exe'
$binario = '"' + $exeGuardiano + '"'
$servizio = Get-Service -Name $NomeServizio -ErrorAction SilentlyContinue
if ($servizio) {
    Esegui 'sc.exe' @('config', $NomeServizio, 'binPath=', $binario, 'start=', 'auto', 'obj=', 'LocalSystem')
}
else {
    New-Service -Name $NomeServizio -BinaryPathName $binario -DisplayName 'Argus - guardiano' -StartupType Automatic | Out-Null
}
Esegui 'sc.exe' @('description', $NomeServizio, 'Argus: apre e riapre il programma di Argus nella sessione dello studente.')
# Se il servizio cade: riparte dopo 5 s, 5 s, poi 30 s; il conteggio si azzera dopo un giorno.
Esegui 'sc.exe' @('failure', $NomeServizio, 'reset=', '86400', 'actions=', 'restart/5000/restart/5000/restart/30000')
Esegui 'sc.exe' @('failureflag', $NomeServizio, '1')
Start-Service -Name $NomeServizio
(Get-Service -Name $NomeServizio).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
Ok 'guardiano acceso (avvio automatico, si riavvia da solo se cade)'

# ---------------------------------------------------------------- 7. menu Start

Passo 'Collegamenti nel menu Start'
New-Item -ItemType Directory -Path $MenuStart -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$l = $shell.CreateShortcut((Join-Path $MenuStart 'Argus - terminale.lnk'))
$l.TargetPath = Join-Path $Destinazione 'Argus.Agente.exe'
$l.Arguments = '--terminale'
$l.WorkingDirectory = $Destinazione
$l.Description = "Apre il terminale di Argus (come $TastoTerminale)"
$l.Save()
$l = $shell.CreateShortcut((Join-Path $MenuStart 'Argus - sblocco d''emergenza.lnk'))
$l.TargetPath = Join-Path $Destinazione 'Argus.Sblocco.exe'
$l.WorkingDirectory = $Destinazione
$l.Description = 'Sblocco d''emergenza (serve la password dell''amministratore)'
$l.Save()
Ok 'fatto'

# ---------------------------------------------------------------- fine

Passo 'Controllo finale'
Start-Sleep -Seconds 5
$agenti = @(Get-Process -Name 'Argus.Agente' -ErrorAction SilentlyContinue)
if ($agenti.Count -gt 0) { Ok "l'agente è acceso (pid $(($agenti | ForEach-Object { $_.Id }) -join ', '))" }
else { Nota "l'agente non è acceso: parte quando entra '$utente' (se è già dentro, entro pochi secondi)." }
if (-not $modelloPronto) { Nota 'modello non pronto: le foto dubbie le guarda il NAS.' }
Write-Host ''
Write-Host 'Argus è installato.' -ForegroundColor Green
Write-Host "Registro del guardiano: $(Join-Path $Dati 'log')"
