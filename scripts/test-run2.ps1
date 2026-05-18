$scriptPath = '<CLAWSEAT_ROOT>'
$scriptContent = Get-Content $scriptPath -Raw
Invoke-Expression $scriptContent
