#Requires -Version 5.1
<#
.SYNOPSIS
    Toglie Argus da questo PC.

.DESCRIPTION
    Da lanciare in Windows PowerShell COME AMMINISTRATORE:

        .\disinstalla.ps1

    Ferma e cancella il servizio "ArgusGuardiano", chiude l'agente, toglie C:\Program Files\Argus, i
    collegamenti del menu Start e C:\ProgramData\Argus (con il segreto dello sblocco: sul NAS resta registrato e
    va cancellato a mano, /data/token-sblocco.txt, prima di installare di nuovo). Il modello (circa 6,5 GB, nella cartella scritta in
    config.json: D:\Argus\modelli o C:\ProgramData\Argus\modelli) resta, così una nuova installazione non lo
    riscarica: per toglierlo aggiungi -TogliModelli. Non tocca LM Studio né altri programmi.

.PARAMETER TogliModelli
    Toglie anche il modello scaricato (solo i file del modello e le cartelle di Argus rimaste vuote).
#>
[CmdletBinding()]
param(
    [switch]$TogliModelli
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$NomeServizio = 'ArgusGuardiano'
$Programma    = Join-Path $env:ProgramFiles 'Argus'
$Dati         = Join-Path $env:ProgramData 'Argus'
$MenuStart    = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Argus'

function Passo([string]$testo) { Write-Host ''; Write-Host "== $testo" -ForegroundColor Cyan }
function Ok([string]$testo) { Write-Host "   $testo" -ForegroundColor Green }
function Attenzione([string]$testo) { Write-Host "   ATTENZIONE: $testo" -ForegroundColor Yellow }

# Una proprietà di un oggetto letto da JSON, o $null se non c'è (con StrictMode leggerla direttamente darebbe errore).
function Proprieta($oggetto, [string]$nome) {
    if ($null -ne $oggetto -and $oggetto.PSObject.Properties[$nome]) { return $oggetto.PSObject.Properties[$nome].Value }
    return $null
}

function Pieno([string]$percorso) { [System.IO.Path]::GetFullPath($percorso).TrimEnd([char]92) }

$io = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $io.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Serve PowerShell aperto come amministratore.' -ForegroundColor Red
    exit 1
}

# Dalla configurazione, prima di cancellarla: l'utente controllato (per togliere i suoi registri) e la
# cartella del modello (può essere su un altro disco, per esempio D:\Argus\modelli).
$utente = $null
$Modelli = Pieno (Join-Path $Dati 'modelli')
try {
    $c = Get-Content -LiteralPath (Join-Path $Dati 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $utente = Proprieta $c 'utente_controllato'
    $modello = Proprieta (Proprieta $c 'motore') 'modello'
    if ($modello) { $Modelli = Pieno (Split-Path -Parent $modello) }
}
catch { }

Passo 'Servizio'
$servizio = Get-Service -Name $NomeServizio -ErrorAction SilentlyContinue
if ($servizio) {
    if ($servizio.Status -ne 'Stopped') {
        Stop-Service -Name $NomeServizio -Force
        $servizio.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
    }
    & sc.exe delete $NomeServizio | Out-Null
    if ($LASTEXITCODE -ne 0) { Attenzione "sc.exe delete ha dato il codice $LASTEXITCODE" } else { Ok 'servizio fermato e cancellato' }
}
else { Ok 'il servizio non c''era' }

Passo 'Programmi di Argus'
# Solo i programmi di Argus: il motore del modello si spegne da solo quando si chiude l'agente.
foreach ($nome in @('Argus.Agente', 'Argus.Sblocco', 'Argus.Guardiano')) {
    Get-Process -Name $nome -ErrorAction SilentlyContinue | ForEach-Object {
        try { $_.Kill(); $_.WaitForExit(5000) | Out-Null; Ok "chiuso $nome (pid $($_.Id))" } catch { Attenzione "non riesco a chiudere $nome (pid $($_.Id))" }
    }
}

Passo 'File'
foreach ($cartella in @($Programma, $MenuStart)) {
    if (Test-Path -LiteralPath $cartella) {
        try { Remove-Item -LiteralPath $cartella -Recurse -Force; Ok "tolto $cartella" }
        catch { Attenzione "non riesco a togliere $cartella ($($_.Exception.Message)). Riavvia il PC e rilancia." }
    }
}

# C:\ProgramData\Argus: tutto tranne la cartella del modello, se sta lì e la si tiene.
if (Test-Path -LiteralPath $Dati) {
    Get-ChildItem -LiteralPath $Dati -Force | Where-Object { $TogliModelli -or (Pieno $_.FullName) -ine $Modelli } | ForEach-Object {
        try { Remove-Item -LiteralPath $_.FullName -Recurse -Force } catch { Attenzione "non riesco a togliere $($_.FullName)" }
    }
    if (-not (Get-ChildItem -LiteralPath $Dati -Force)) {
        Remove-Item -LiteralPath $Dati -Force -ErrorAction SilentlyContinue
        Ok "tolto $Dati"
    }
    else { Ok "tolto $Dati tranne il modello" }
}

# Il modello fuori da ProgramData: si toglie solo con -TogliModelli, e solo i suoi file (*.gguf e i pezzi
# .part), poi le cartelle rimaste vuote (la cartella del modello e, se si chiama Argus, quella sopra).
if (Test-Path -LiteralPath $Modelli) {
    if ($TogliModelli) {
        Get-ChildItem -LiteralPath $Modelli -Force -File | Where-Object { $_.Name -like '*.gguf' -or $_.Name -like '*.gguf.part' } | ForEach-Object {
            try { Remove-Item -LiteralPath $_.FullName -Force } catch { Attenzione "non riesco a togliere $($_.FullName)" }
        }
        if (-not (Get-ChildItem -LiteralPath $Modelli -Force)) {
            Remove-Item -LiteralPath $Modelli -Force -ErrorAction SilentlyContinue
            $sopra = Split-Path -Parent $Modelli
            if ((Split-Path -Leaf $sopra) -ieq 'Argus' -and $sopra.Length -gt 3 -and -not (Get-ChildItem -LiteralPath $sopra -Force)) {
                Remove-Item -LiteralPath $sopra -Force -ErrorAction SilentlyContinue
            }
            Ok "tolto il modello ($Modelli)"
        }
        else { Attenzione "in $Modelli sono rimasti altri file: la cartella resta." }
    }
    else { Ok "il modello resta in $Modelli (per toglierlo: -TogliModelli)" }
}

# I dati dell'agente nel profilo dello studente: registri e cartella del terminale.
if ($utente) {
    $profilo = Get-CimInstance Win32_UserProfile -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPath -and ((Split-Path $_.LocalPath -Leaf) -ieq $utente) } | Select-Object -First 1
    if ($profilo) {
        $suoi = Join-Path $profilo.LocalPath 'AppData\Local\Argus'
        if (Test-Path -LiteralPath $suoi) {
            try { Remove-Item -LiteralPath $suoi -Recurse -Force; Ok "tolto $suoi" } catch { Attenzione "non riesco a togliere $suoi" }
        }
    }
}

Write-Host ''
Write-Host 'Argus è stato tolto.' -ForegroundColor Green
# Il segreto dello sblocco se n'è andato con config.json, ma sul NAS resta registrato.
Write-Host 'Per installarlo di nuovo: chi gestisce il NAS deve prima cancellare /data/token-sblocco.txt (il segreto dello sblocco di questa installazione).'
