[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $CorpusRoot,
    [Parameter(Mandatory = $true)] [string] $NormalizationManifest,
    [Parameter(Mandatory = $true)] [string] $OutputPath
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

function Normalize-Title([string] $Value) {
    if ($null -eq $Value) { return '' }
    $normalized = $Value.Normalize([System.Text.NormalizationForm]::FormKC)
    $normalized = $normalized.Replace([char]13, ' ').Replace([char]7, ' ').Replace([char]11, ' ')
    return ([regex]::Replace($normalized, '\s+', ' ')).Trim()
}

function Get-Sha256([string] $PathValue) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $PathValue).Hash.ToLowerInvariant()
}

function Get-HeadingStyleLevel([string] $StyleName) {
    if ($StyleName -match '(?i)heading\s*([1-9])|标题\s*([1-9])') {
        if ($matches[1]) { return [int] $matches[1] }
        if ($matches[2]) { return [int] $matches[2] }
    }
    return 0
}

function Write-JsonAtomic([string] $PathValue, [object] $Payload) {
    $target = Resolve-FullPath $PathValue
    $parent = Split-Path -Parent $target
    [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = $target + '.partial'
    if ((Test-Path -LiteralPath $temporary) -or (Test-Path -LiteralPath $target)) {
        throw 'Refusing to overwrite an existing Word outline artifact'
    }
    $json = $Payload | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $target
}

$corpusRootFull = Resolve-FullPath $CorpusRoot
$rawRoot = Resolve-FullPath (Join-Path $corpusRootFull 'raw')
$outputFull = Assert-UnderRoot $OutputPath $corpusRootFull 'Output path'
$manifestPath = Resolve-FullPath $NormalizationManifest
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$word = $null
$documents = [System.Collections.Generic.List[object]]::new()

try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    try { $word.Options.UpdateLinksAtOpen = $false } catch { }
    try { $word.Options.SaveNormalPrompt = $false } catch { }
    try { $word.WordBasic.DisableAutoMacros(1) } catch { }

    foreach ($item in $manifest.documents) {
        if ($item.status -ne 'success' -or ([string] $item.source_extension).ToLowerInvariant() -ne '.doc') {
            continue
        }
        $documentId = [string] $item.document_id
        if ($documentId -notmatch '^rdv2-[0-9a-f]{16}$') {
            throw 'Normalization manifest contains an invalid document ID'
        }
        $stagedPath = Assert-UnderRoot (Join-Path $corpusRootFull ([string] $item.staged_relative_path)) $rawRoot 'Staged Word path'
        if (-not (Test-Path -LiteralPath $stagedPath -PathType Leaf)) {
            throw 'Staged Word copy is missing'
        }
        $stagedHash = Get-Sha256 $stagedPath
        if ($stagedHash -ne [string] $item.source_sha256) {
            throw 'Staged Word hash differs from source manifest hash'
        }

        $doc = $null
        try {
            $doc = $word.Documents.Open($stagedPath, $false, $true, $false)
            if (-not $doc.ReadOnly) { throw 'Word did not honor read-only mode' }
            $headings = [System.Collections.Generic.List[object]]::new()
            $ordinal = 0
            foreach ($paragraph in $doc.Paragraphs) {
                $ordinal += 1
                $range = $paragraph.Range
                $title = Normalize-Title ([string] $range.Text)
                if ([string]::IsNullOrWhiteSpace($title)) { continue }
                $styleName = ''
                try { $styleName = [string] $range.Style.NameLocal } catch { }
                $styleLevel = Get-HeadingStyleLevel $styleName
                $outlineLevel = 10
                try { $outlineLevel = [int] $paragraph.OutlineLevel } catch { }
                $headingStyle = $styleLevel -ge 1
                $outlineCandidate = $outlineLevel -ge 1 -and $outlineLevel -le 9
                if (-not ($headingStyle -or $outlineCandidate)) { continue }
                $inTable = $false
                try { $inTable = [bool] $range.Information(12) } catch { }
                $pageNumber = 0
                try { $pageNumber = [int] $range.Information(3) } catch { }
                $numberingLabel = ''
                try {
                    if ([int] $range.ListFormat.ListType -ne 0) {
                        $numberingLabel = Normalize-Title ([string] $range.ListFormat.ListString)
                    }
                } catch { }
                $level = if ($outlineCandidate) { $outlineLevel } elseif ($headingStyle) { $styleLevel } else { 1 }
                $headings.Add([ordered]@{
                    normalized_title = $title
                    level = $level
                    source_page_hint = $pageNumber
                    source_ordinal = $ordinal
                    numbering_label = $numberingLabel
                    heading_style = $headingStyle
                    outline_candidate = $outlineCandidate
                    in_table = $inTable
                })
            }
            $documents.Add([ordered]@{
                document_id = $documentId
                source_file_hash = $stagedHash
                extractor = 'WORD_COM_READ_ONLY'
                opened_read_only = $true
                macros_forced_disabled = $true
                heading_count = $headings.Count
                headings = $headings
                body_text_included = $false
            })
            $doc.Close(0)
            $doc = $null
        } catch {
            if ($null -ne $doc) {
                try { $doc.Close(0) } catch { }
                $doc = $null
            }
            throw 'Legacy Word outline extraction failed; details redacted'
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
    extractor_version = 'rd-v2-word-com/1.0'
    inspection_mode = 'word_com_read_only_staged_hash_identical_copy'
    online_services_used = $false
    macros_executed = $false
    documents = $documents
}
Write-JsonAtomic $outputFull $payload
@($documents | ForEach-Object {
    [ordered]@{ document_id = $_.document_id; headings = $_.heading_count; read_only = $_.opened_read_only }
}) | ConvertTo-Json -Compress
