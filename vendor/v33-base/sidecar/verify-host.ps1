param(
    [Parameter(Mandatory)][ValidateRange(1,65535)][int]$RpcPort,
    [Parameter(Mandatory)][string]$Cloud,
    [Parameter(Mandatory)][string]$Api,
    [Parameter(Mandatory)][string]$Inference
)
$ErrorActionPreference = 'Stop'
$expectedRoot = Join-Path $env:LOCALAPPDATA 'Programs\antigravity'
$lsPath = Join-Path $expectedRoot 'resources\bin\language_server.exe'
$appPath = Join-Path $expectedRoot 'Antigravity.exe'
$lsDigest = '73CE9A2405B455A93D1F13DB2AE555DA50406110217A349B6DD85C377FBDB9D1'
$owners = @(Get-NetTCPConnection -State Listen -LocalPort $RpcPort -ErrorAction Stop |
    Where-Object { $_.LocalAddress -in @('127.0.0.1','::1') } |
    Select-Object -ExpandProperty OwningProcess -Unique)
if ($owners.Count -ne 1) { throw 'Unexpected language service listener' }
$ls = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $owners[0])
$desktop = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ls.ParentProcessId)
if ($ls.ExecutablePath -ne $lsPath -or $desktop.ExecutablePath -ne $appPath) { throw 'Unexpected process tree' }
if ((Get-Item -LiteralPath $appPath).VersionInfo.FileVersion -ne '2.35.1' -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $lsPath).Hash -ne $lsDigest) { throw 'Unsupported build' }
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
