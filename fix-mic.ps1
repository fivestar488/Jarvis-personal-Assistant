# Checks the Windows and Edge settings Jarvis's microphone needs, and fixes what it can.
# Run it through fix-mic.bat. "-CheckOnly" just reports.
param([switch]$CheckOnly)

$consent = "Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
$problems = 0

function Report($ok, $text, $how) {
    if ($ok) { Write-Host "  [OK]      $text" -ForegroundColor Green }
    else { Write-Host "  [PROBLEM] $text" -ForegroundColor Yellow; if ($how) { Write-Host "            $how" }; $script:problems++ }
}
function Get-Reg($key, $name) { (Get-ItemProperty -Path $key -Name $name -ErrorAction SilentlyContinue).$name }

Write-Host "`nChecking what Jarvis's microphone needs...`n"

# 1. Windows microphone privacy. A missing value means Windows' default, which is allowed.
$pc = Get-Reg "HKLM:\$consent" "Value"
Report ($pc -ne "Deny") "Microphone access is on for this PC" "Settings > Privacy & security > Microphone > turn on 'Microphone access' (opening it for you)"
if ($pc -eq "Deny" -and -not $CheckOnly) { Start-Process "ms-settings:privacy-microphone" }

foreach ($c in @(@{Key = "HKCU:\$consent"; Text = "Apps may use the microphone"},
                 @{Key = "HKCU:\$consent\NonPackaged"; Text = "Desktop apps (Edge) may use the microphone"})) {
    $ok = (Get-Reg $c.Key "Value") -ne "Deny"
    Report $ok $c.Text $(if ($CheckOnly) { "Settings > Privacy & security > Microphone" } else { "Fixed: switched it on." })
    if (-not $ok -and -not $CheckOnly) { Set-ItemProperty -Path $c.Key -Name "Value" -Value "Allow" }
}

# 2. Edge turns speech into text through Microsoft's online service, so it needs the internet.
$online = Test-NetConnection "speech.platform.bing.com" -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue
Report $online "Can reach Microsoft's speech service" "Check the internet connection, and any VPN, firewall or antivirus web filter."

# 3. Whether Edge has blocked the microphone for the Jarvis page (setting 2 = blocked).
$blocked = @()
Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Edge\User Data" -Filter Preferences -Recurse -Depth 1 -ErrorAction SilentlyContinue | ForEach-Object {
    $mic = (Get-Content $_.FullName -Raw | ConvertFrom-Json).profile.content_settings.exceptions.media_stream_mic
    if ($mic) { $mic.PSObject.Properties | Where-Object { $_.Name -match ":8765" -and $_.Value.setting -eq 2 } | ForEach-Object { $blocked += $_.Name } }
}
Report ($blocked.Count -eq 0) "Edge isn't blocking the microphone for Jarvis" "In the Jarvis window: ... (top right) > Site permissions > Microphone > Allow, then press F5."

# 4. A microphone is plugged in and working.
$mics = @(Get-PnpDevice -Class AudioEndpoint -Status OK -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -like "*{0.0.1.00000000}*" })
Report ($mics.Count -gt 0) "A microphone is connected ($(($mics.FriendlyName) -join ', '))" "No working microphone found. Plug one in, or check Settings > System > Sound > Input."

Write-Host ""
if ($problems -eq 0) { Write-Host "Everything looks right. Close and reopen Jarvis, then click the mic." -ForegroundColor Green }
elseif ($CheckOnly) { Write-Host "$problems thing(s) to fix - see above." -ForegroundColor Yellow }
else { Write-Host "Done. Close Jarvis (both windows) and start jarvis.bat again, then click the mic." -ForegroundColor Green }
