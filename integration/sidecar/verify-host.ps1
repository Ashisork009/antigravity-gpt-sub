param(
    [Parameter(Mandatory)][ValidateRange(1,65535)][int]$RpcPort,
    [Parameter(Mandatory)][string]$Cloud,
    [Parameter(Mandatory)][string]$Api,
    [Parameter(Mandatory)][string]$Inference
)
$ErrorActionPreference = 'Stop'
$appGuid = '121a0be4-63bd-531e-acf8-fc3924c7e984'
$allowedRoots = New-Object System.Collections.Generic.List[string]
foreach ($regPath in @("HKCU:\Software\$appGuid", "HKLM:\Software\$appGuid")) {
    try {
        $loc = Get-ItemPropertyValue -LiteralPath $regPath -Name 'InstallLocation' -ErrorAction Stop
        if ($loc -is [string] -and $loc.Trim()) {
            $trimmed = $loc.Trim().TrimEnd('\','/')
            if (Test-Path -LiteralPath $trimmed -PathType Container) {
                $item = Get-Item -LiteralPath $trimmed -ErrorAction Stop
                if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                    $full = $item.FullName.TrimEnd('\','/')
                    if ($allowedRoots -notcontains $full) { $allowedRoots.Add($full) }
                }
            }
        }
    } catch {}
}
$defaultRoot = Join-Path $env:LOCALAPPDATA 'Programs\antigravity'
if ($allowedRoots -notcontains $defaultRoot) { $allowedRoots.Add($defaultRoot) }
$owners = @(Get-NetTCPConnection -State Listen -LocalPort $RpcPort -ErrorAction Stop |
    Where-Object { $_.LocalAddress -in @('127.0.0.1','::1') } |
    Select-Object -ExpandProperty OwningProcess -Unique)
if ($owners.Count -ne 1) { throw 'Unexpected language service listener' }
$ls = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $owners[0])
$desktop = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ls.ParentProcessId)
$matchedRoot = $null
$lsPath = $null
$appPath = $null
foreach ($root in $allowedRoots) {
    $candLs = Join-Path $root 'resources\bin\language_server.exe'
    $candApp = Join-Path $root 'Antigravity.exe'
    if ($ls.ExecutablePath -eq $candLs -and $desktop.ExecutablePath -eq $candApp) {
        $matchedRoot = $root
        $lsPath = $candLs
        $appPath = $candApp
        break
    }
}
if (-not $matchedRoot) { throw 'Unexpected process tree' }
if ((Get-Item -LiteralPath $appPath).VersionInfo.FileVersion -ne '2.36.0') { throw 'Unsupported build' }
$isProduction = -not [regex]::IsMatch($ls.CommandLine, '(?:^|\s)--inference_api_server_url(?:=|\s|$)')
$flags = @{ '--cloud_code_endpoint'=$Cloud }
if ($isProduction) {
    $flags['--api_server_url'] = 'https://generativelanguage.googleapis.com'
} else {
    $flags['--api_server_url'] = $Api
    $flags['--inference_api_server_url'] = $Inference
}
foreach ($item in $flags.GetEnumerator()) {
    $value = [uri]$item.Value
    if (($item.Key -ne '--api_server_url' -or -not $isProduction) -and
        ($value.Scheme -ne 'http' -or $value.Host -ne '127.0.0.1' -or
        $value.GetLeftPart([UriPartial]::Authority) -ne $item.Value)) { throw 'Unexpected endpoint' }
    $matchesAll = [regex]::Matches($ls.CommandLine, '(?:^|\s)' + $item.Key + '(?:=|\s+)"?([^\s"]+)"?(?=\s|$)')
    if ($matchesAll.Count -ne 1 -or $matchesAll[0].Groups[1].Value -cne $item.Value) { throw 'Language service endpoints changed' }
}
$pinned = Get-Process -Id $ls.ProcessId -ErrorAction Stop
if ($pinned.Path -ne $lsPath) { throw 'Language service changed during verification' }
Write-Output ("{0} {1}" -f $pinned.Id, $pinned.StartTime.ToUniversalTime().ToFileTimeUtc())
