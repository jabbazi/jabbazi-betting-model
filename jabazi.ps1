param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $JabaziArguments
)

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Jabazi is not installed. Create .venv and install the project first.'
}

& $python -m jabazi @JabaziArguments
exit $LASTEXITCODE
