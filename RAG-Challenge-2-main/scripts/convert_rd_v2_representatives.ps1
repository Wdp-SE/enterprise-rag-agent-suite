[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $SourceRoot,
    [Parameter(Mandatory = $true)] [string] $CorpusRoot,
    [Parameter(Mandatory = $true)] [string] $SelectionManifest,
    [Parameter(Mandatory = $true)] [string] $OutputManifest,
    [switch] $ResumeValidatedExisting
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Resolve-FullPath([string] $PathValue) {
    return [System.IO.Path]::GetFullPath($PathValue).TrimEnd('\')
}

function Assert-UnderRoot([string] $Candidate, [string] $Root, [string] $Label) {
    $candidateFull = Resolve-FullPath $Candidate
    $rootFull = Resolve-FullPath $Root
    if (-not $candidateFull.StartsWith($rootFull + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label is outside its allowed root"
    }
    return $candidateFull
}

function Get-Sha256([string] $PathValue) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $PathValue).Hash.ToLowerInvariant()
}

function Write-JsonAtomic([string] $PathValue, [object] $Payload) {
    $target = Resolve-FullPath $PathValue
    $parent = Split-Path -Parent $target
    [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = $target + '.partial'
    if (Test-Path -LiteralPath $temporary) {
        throw 'Refusing to overwrite an existing partial manifest'
    }
    $json = $Payload | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $target
}

$sourceRootFull = Resolve-FullPath $SourceRoot
$corpusRootFull = Resolve-FullPath $CorpusRoot
$rawRoot = Join-Path $corpusRootFull 'raw'
$normalizedRoot = Join-Path $corpusRootFull 'normalized\pdfs'
[System.IO.Directory]::CreateDirectory($rawRoot) | Out-Null
[System.IO.Directory]::CreateDirectory($normalizedRoot) | Out-Null

$selectionPath = Resolve-FullPath $SelectionManifest
$selection = Get-Content -Raw -LiteralPath $selectionPath | ConvertFrom-Json
if ($selection.selected_count -lt 1 -or $selection.selected_count -gt 3) {
    throw 'Selection manifest must contain between one and three documents'
}
if (Test-Path -LiteralPath $OutputManifest) {
    throw 'Refusing to overwrite an existing normalization manifest'
}

$word = $null
$results = [System.Collections.Generic.List[object]]::new()
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
    try { $word.Options.UpdateLinksAtOpen = $false } catch { }
    try { $word.WordBasic.DisableAutoMacros(1) } catch { }

    foreach ($item in $selection.documents) {
        $documentId = [string] $item.document_id
        if ($documentId -notmatch '^rdv2-[0-9a-f]{16}$') {
            throw 'Selection manifest contains an invalid deterministic document ID'
        }
        $sourcePath = Assert-UnderRoot (Join-Path $sourceRootFull ([string] $item.source_relative_path)) $sourceRootFull 'Source path'
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw 'Selected source file no longer exists'
        }
        $extension = [System.IO.Path]::GetExtension($sourcePath).ToLowerInvariant()
        if ($extension -notin @('.doc', '.docx')) {
            throw 'Only .doc and .docx are accepted by this local normalization utility'
        }
        $sourceHashBefore = Get-Sha256 $sourcePath
        if ($sourceHashBefore -ne [string] $item.source_sha256) {
            throw 'Selected source hash differs from the read-only inventory'
        }

        $stagedPath = Assert-UnderRoot (Join-Path $rawRoot ($documentId + $extension)) $rawRoot 'Staging path'
        $canonicalPath = Assert-UnderRoot (Join-Path $normalizedRoot ($documentId + '.pdf')) $normalizedRoot 'Canonical path'
        $partialPdf = Assert-UnderRoot (Join-Path $normalizedRoot ($documentId + '.partial.pdf')) $normalizedRoot 'Partial PDF path'

        if (Test-Path -LiteralPath $stagedPath) {
            if ((Get-Sha256 $stagedPath) -ne $sourceHashBefore) {
                throw 'Existing staging copy hash mismatch'
            }
        } else {
            Copy-Item -LiteralPath $sourcePath -Destination $stagedPath
        }
        if (Test-Path -LiteralPath $partialPdf) {
            throw 'Refusing to overwrite an existing partial PDF'
        }

        if (Test-Path -LiteralPath $canonicalPath) {
            if (-not $ResumeValidatedExisting) {
                throw 'Refusing to overwrite an existing canonical PDF'
            }
            if ((Get-Item -LiteralPath $canonicalPath).Length -le 0) {
                throw 'Validated existing canonical PDF is empty'
            }
            $sourceHashAfter = Get-Sha256 $sourcePath
            if ($sourceHashAfter -ne $sourceHashBefore) {
                throw 'Source file changed before conversion resume'
            }
            $results.Add([ordered]@{
                document_id = $documentId
                document_type = [string] $item.document_type
                source_file_name = [string] $item.source_file_name
                source_relative_path = [string] $item.source_relative_path
                source_extension = $extension
                source_size = [long] $item.source_size
                source_sha256 = $sourceHashBefore
                staged_relative_path = [System.IO.Path]::GetRelativePath($corpusRootFull, $stagedPath).Replace('\', '/')
                staged_sha256 = Get-Sha256 $stagedPath
                normalized_relative_path = [System.IO.Path]::GetRelativePath($corpusRootFull, $canonicalPath).Replace('\', '/')
                normalized_size = (Get-Item -LiteralPath $canonicalPath).Length
                normalized_sha256 = Get-Sha256 $canonicalPath
                converter = 'Microsoft Word local COM ExportAsFixedFormat'
                converter_version = [string] $word.Version
                macros_forced_disabled = $true
                source_opened_read_only = $true
                resumed_validated_existing = $true
                status = 'success'
            })
            continue
        }

        $document = $null
        try {
            # Open only the deterministic staging copy. ConfirmConversions=false,
            # ReadOnly=true, AddToRecentFiles=false.
            $document = $word.Documents.Open($stagedPath, $false, $true, $false)
            if (-not $document.ReadOnly) {
                throw 'Word did not honor read-only open mode'
            }
            $document.ExportAsFixedFormat($partialPdf, 17)  # wdExportFormatPDF
            $document.Close(0)
            $document = $null
            if (-not (Test-Path -LiteralPath $partialPdf -PathType Leaf)) {
                throw 'Word conversion did not produce a PDF'
            }
            if ((Get-Item -LiteralPath $partialPdf).Length -le 0) {
                throw 'Word conversion produced an empty PDF'
            }
            Move-Item -LiteralPath $partialPdf -Destination $canonicalPath
            $sourceHashAfter = Get-Sha256 $sourcePath
            if ($sourceHashAfter -ne $sourceHashBefore) {
                throw 'Source file changed during local conversion'
            }
            $results.Add([ordered]@{
                document_id = $documentId
                document_type = [string] $item.document_type
                source_file_name = [string] $item.source_file_name
                source_relative_path = [string] $item.source_relative_path
                source_extension = $extension
                source_size = [long] $item.source_size
                source_sha256 = $sourceHashBefore
                staged_relative_path = [System.IO.Path]::GetRelativePath($corpusRootFull, $stagedPath).Replace('\', '/')
                staged_sha256 = Get-Sha256 $stagedPath
                normalized_relative_path = [System.IO.Path]::GetRelativePath($corpusRootFull, $canonicalPath).Replace('\', '/')
                normalized_size = (Get-Item -LiteralPath $canonicalPath).Length
                normalized_sha256 = Get-Sha256 $canonicalPath
                converter = 'Microsoft Word local COM ExportAsFixedFormat'
                converter_version = [string] $word.Version
                macros_forced_disabled = $true
                source_opened_read_only = $true
                status = 'success'
            })
        } catch {
            if ($null -ne $document) {
                try { $document.Close(0) } catch { }
                $document = $null
            }
            if (Test-Path -LiteralPath $partialPdf) {
                $resolvedPartial = Assert-UnderRoot $partialPdf $normalizedRoot 'Partial cleanup path'
                Remove-Item -LiteralPath $resolvedPartial -Force
            }
            $results.Add([ordered]@{
                document_id = $documentId
                document_type = [string] $item.document_type
                source_file_name = [string] $item.source_file_name
                source_relative_path = [string] $item.source_relative_path
                source_extension = $extension
                source_sha256 = $sourceHashBefore
                converter = 'Microsoft Word local COM ExportAsFixedFormat'
                macros_forced_disabled = $true
                source_opened_read_only = $true
                status = 'failed'
                failure_type = $_.Exception.GetType().Name
            })
        }
    }
} finally {
    if ($null -ne $word) {
        try { $word.Quit() } catch { }
        [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) | Out-Null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$payload = [ordered]@{
    schema_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_root = $sourceRootFull
    corpus_root = $corpusRootFull
    selection_count = [int] $selection.selected_count
    online_converter_used = $false
    macros_executed = $false
    source_files_opened_by_word = $false
    staged_copies_opened_read_only = $true
    documents = $results
}
Write-JsonAtomic $OutputManifest $payload

$successCount = @($results | Where-Object { $_.status -eq 'success' }).Count
$failureCount = @($results | Where-Object { $_.status -eq 'failed' }).Count
[ordered]@{ selected = $results.Count; success = $successCount; failed = $failureCount } | ConvertTo-Json -Compress
if ($failureCount -gt 0) { exit 2 }
