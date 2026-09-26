param(
    [Parameter(Mandatory=$true)][string]$InputDocx,
    [Parameter(Mandatory=$true)][string]$OutputPdf
)

$ErrorActionPreference = 'Stop'

$source = [IO.Path]::GetFullPath($InputDocx)
$target = [IO.Path]::GetFullPath($OutputPdf)
$workspace = [IO.Path]::GetFullPath((Get-Location).Path).TrimEnd('\')
if (-not $target.StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'PDF output must stay inside the workspace'
}
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw 'DOCX input does not exist'
}
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$document = $null
try {
    $document = $word.Documents.Open($source, $false, $true)
    $document.ExportAsFixedFormat($target, 17)
} finally {
    if ($null -ne $document) { $document.Close($false) }
    $word.Quit()
}
Write-Output "pdf=$target"
