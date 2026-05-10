param(
    [Parameter(Mandatory = $true)]
    [string]$ImportDir,

    [string]$SourceDir = "data\pubevent_soa_lite\graph\neo4j_import"
)

$ErrorActionPreference = "Stop"

$resolvedSource = Resolve-Path -LiteralPath $SourceDir
if (-not (Test-Path -LiteralPath $ImportDir)) {
    New-Item -ItemType Directory -Path $ImportDir | Out-Null
}
$resolvedImport = Resolve-Path -LiteralPath $ImportDir

$files = Get-ChildItem -LiteralPath $resolvedSource -Filter "*.csv" -File
if ($files.Count -eq 0) {
    throw "No CSV files found in $resolvedSource. Run: python scripts/export_neo4j_graph.py"
}

foreach ($file in $files) {
    Copy-Item -LiteralPath $file.FullName -Destination $resolvedImport -Force
}

Write-Host "Copied $($files.Count) CSV files to $resolvedImport"
Write-Host "Now run data\pubevent_soa_lite\graph\neo4j_import\import.cypher in Neo4j Query."
