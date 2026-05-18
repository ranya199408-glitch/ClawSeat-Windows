$content = Get-Content '<CLAWSEAT_ROOT>' -Raw
$errors = $null
[System.Management.Automation.PSParser]::Tokenize($content, [ref]$errors)
if ($errors.Count -gt 0) {
    foreach ($e in $errors) {
        Write-Output ('Line ' + $e.Token.StartLine + ': ' + $e.Message)
    }
} else {
    Write-Output 'No parse errors found'
}
