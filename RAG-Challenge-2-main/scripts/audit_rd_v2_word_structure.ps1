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

function Get-Sha256([string] $PathValue) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $PathValue).Hash.ToLowerInvariant()
}

function Get-TextSha256([string] $Value) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Normalize-Text([string] $Value) {
    if ($null -eq $Value) { return '' }
    $normalized = $Value.Replace([char]13, ' ').Replace([char]7, ' ').Replace([char]11, ' ')
    return ([regex]::Replace($normalized, '\s+', ' ')).Trim()
}

function Get-StyleClass([string] $StyleName) {
    if ([string]::IsNullOrWhiteSpace($StyleName)) { return 'UNKNOWN' }
    if ($StyleName -match '(?i)heading\s*[1-9]|标题\s*[1-9]') { return 'HEADING' }
    if ($StyleName -match '(?i)^title$|^标题$') { return 'TITLE' }
    if ($StyleName -match '(?i)toc|目录') { return 'TOC' }
    if ($StyleName -match '(?i)caption|题注') { return 'CAPTION' }
    if ($StyleName -match '(?i)normal|正文|body\s*text') { return 'BODY' }
    return 'CUSTOM'
}

function Get-ListTypeClass([int] $ListType) {
    switch ($ListType) {
        0 { return 'NONE' }
        1 { return 'LISTNUM_FIELD' }
        2 { return 'BULLET' }
        3 { return 'SIMPLE_NUMBERING' }
        4 { return 'OUTLINE_NUMBERING' }
        5 { return 'MIXED_NUMBERING' }
        6 { return 'PICTURE_BULLET' }
        default { return 'OTHER' }
    }
}

function Get-PrefixPattern([string] $Text) {
    if ($Text -match '^\s*\d+(?:\.\d+){1,5}[.、]?\s+') { return 'ARABIC_HIERARCHY_SPACED' }
    if ($Text -match '^\s*\d+(?:\.\d+){1,5}[.、]?(?=\S)') { return 'ARABIC_HIERARCHY_TIGHT' }
    if ($Text -match '^\s*\d+[.、]\s+') { return 'ARABIC_SINGLE_SPACED' }
    if ($Text -match '^\s*\d+[.、](?=\S)') { return 'ARABIC_SINGLE_TIGHT' }
    if ($Text -match '^\s*[（(]\d+[）)]') { return 'PAREN_ARABIC' }
    if ($Text -match '^\s*第\s*[0-9零〇一二三四五六七八九十百千两]+\s*(章|节|部分)') { return 'CHAPTER' }
    if ($Text -match '^\s*[零〇一二三四五六七八九十百千两]+、') { return 'CHINESE_ENUMERATION' }
    if ($Text -match '^\s*[（(][零〇一二三四五六七八九十百千两]+[）)]') { return 'PAREN_CHINESE' }
    if ($Text -match '^\s*[-•·●○■□◆◇]') { return 'BULLET_LIKE' }
    return 'NONE'
}

function Get-LengthBucket([int] $Length) {
    if ($Length -le 10) { return '1_10' }
    if ($Length -le 30) { return '11_30' }
    if ($Length -le 60) { return '31_60' }
    if ($Length -le 120) { return '61_120' }
    return '121_PLUS'
}

function Write-JsonAtomic([string] $PathValue, [object] $Payload) {
    $target = Resolve-FullPath $PathValue
    $parent = Split-Path -Parent $target
    [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = $target + '.partial'
    if (Test-Path -LiteralPath $temporary) {
        throw 'Refusing to overwrite an existing partial audit artifact'
    }
    $json = $Payload | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $target
}

$corpusRootFull = Resolve-FullPath $CorpusRoot
$rawRoot = Resolve-FullPath (Join-Path $corpusRootFull 'raw')
$outputFull = Assert-UnderRoot $OutputPath $corpusRootFull 'Output path'
$manifest = Get-Content -Raw -LiteralPath (Resolve-FullPath $NormalizationManifest) | ConvertFrom-Json

$word = $null
$documentResults = [System.Collections.Generic.List[object]]::new()
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    try { $word.Options.UpdateLinksAtOpen = $false } catch { }
    try { $word.WordBasic.DisableAutoMacros(1) } catch { }

    foreach ($item in $manifest.documents) {
        if ($item.status -ne 'success') { continue }
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

            $records = [System.Collections.Generic.List[object]]::new()
            $styleCounts = @{}
            $prefixCounts = @{}
            $listTypeCounts = @{}
            $outlineCounts = @{}
            $nonEmpty = 0
            $inTableCount = 0
            $headingStyleCount = 0
            $outlineCandidateCount = 0
            $automaticNumberingCount = 0
            $numberedStructuralCount = 0
            $ordinal = 0

            foreach ($paragraph in $doc.Paragraphs) {
                $ordinal += 1
                $range = $paragraph.Range
                $text = Normalize-Text ([string] $range.Text)
                if ([string]::IsNullOrWhiteSpace($text)) { continue }
                $nonEmpty += 1

                $styleName = ''
                try { $styleName = [string] $range.Style.NameLocal } catch { }
                $styleClass = Get-StyleClass $styleName
                $outlineLevel = 10
                try { $outlineLevel = [int] $paragraph.OutlineLevel } catch { }
                $listType = 0
                $listLevel = 0
                $listMarker = ''
                try {
                    $listType = [int] $range.ListFormat.ListType
                    if ($listType -ne 0) {
                        $listLevel = [int] $range.ListFormat.ListLevelNumber
                        $listMarker = Normalize-Text ([string] $range.ListFormat.ListString)
                    }
                } catch { }
                $inTable = $false
                try { $inTable = [bool] $range.Information(12) } catch { }
                $prefixPattern = Get-PrefixPattern $text
                $listTypeClass = Get-ListTypeClass $listType
                $isOutline = $outlineLevel -ge 1 -and $outlineLevel -le 9
                $isHeadingStyle = $styleClass -eq 'HEADING'
                $isNumbered = $listType -ne 0
                # Word pagination is expensive on very long documents. Page
                # anchors are needed only for structural/numbered candidates;
                # ordinary body paragraphs retain page_number=0 and can still
                # be matched by their SHA256 when required.
                $pageNumber = 0
                if ($isOutline -or $isHeadingStyle -or $isNumbered -or $prefixPattern -ne 'NONE') {
                    try { $pageNumber = [int] $range.Information(3) } catch { }
                }

                if (-not $styleCounts.ContainsKey($styleClass)) { $styleCounts[$styleClass] = 0 }
                if (-not $prefixCounts.ContainsKey($prefixPattern)) { $prefixCounts[$prefixPattern] = 0 }
                if (-not $listTypeCounts.ContainsKey($listTypeClass)) { $listTypeCounts[$listTypeClass] = 0 }
                if (-not $outlineCounts.ContainsKey([string] $outlineLevel)) { $outlineCounts[[string] $outlineLevel] = 0 }
                $styleCounts[$styleClass] += 1
                $prefixCounts[$prefixPattern] += 1
                $listTypeCounts[$listTypeClass] += 1
                $outlineCounts[[string] $outlineLevel] += 1
                if ($inTable) { $inTableCount += 1 }
                if ($isHeadingStyle) { $headingStyleCount += 1 }
                if ($isOutline) { $outlineCandidateCount += 1 }
                if ($isNumbered) { $automaticNumberingCount += 1 }
                if ($isNumbered -and ($isOutline -or $isHeadingStyle)) { $numberedStructuralCount += 1 }

                $markerPattern = ''
                if (-not [string]::IsNullOrWhiteSpace($listMarker)) {
                    $markerPattern = $listMarker
                    $markerPattern = [regex]::Replace($markerPattern, '[0-9]', 'D')
                    $markerPattern = [regex]::Replace($markerPattern, '[A-Za-z]', 'A')
                    $markerPattern = [regex]::Replace($markerPattern, '[零〇一二三四五六七八九十百千两]', 'C')
                    if ($markerPattern.Length -gt 24) { $markerPattern = $markerPattern.Substring(0, 24) }
                }

                $records.Add([ordered]@{
                    ordinal = $ordinal
                    normalized_text_sha256 = Get-TextSha256 $text
                    text_length_bucket = Get-LengthBucket $text.Length
                    page_number = $pageNumber
                    style_class = $styleClass
                    outline_level = $outlineLevel
                    list_type = $listTypeClass
                    list_level = $listLevel
                    list_marker_pattern = $markerPattern
                    prefix_pattern = $prefixPattern
                    in_table = $inTable
                    heading_style = $isHeadingStyle
                    outline_candidate = $isOutline
                    automatic_numbering = $isNumbered
                    ends_with_colon = $text.EndsWith(':') -or $text.EndsWith('：')
                    sentence_terminal = $text.EndsWith('。') -or $text.EndsWith('.') -or $text.EndsWith('；') -or $text.EndsWith(';')
                })
            }

            $computedPages = 0
            try { $computedPages = [int] $doc.ComputeStatistics(2) } catch { }
            $documentResults.Add([ordered]@{
                document_id = $documentId
                document_type = [string] $item.document_type
                source_extension = [string] $item.source_extension
                source_sha256 = [string] $item.source_sha256
                staged_sha256 = $stagedHash
                inspected_copy = 'deterministic_staged_copy'
                opened_read_only = $true
                macros_forced_disabled = $true
                word_version = [string] $word.Version
                computed_pages = $computedPages
                paragraph_count = [int] $doc.Paragraphs.Count
                nonempty_paragraph_count = $nonEmpty
                table_count = [int] $doc.Tables.Count
                paragraphs_in_tables = $inTableCount
                word_list_count = [int] $doc.Lists.Count
                toc_count = [int] $doc.TablesOfContents.Count
                field_count = [int] $doc.Fields.Count
                heading_style_paragraphs = $headingStyleCount
                outline_level_paragraphs = $outlineCandidateCount
                automatic_numbering_paragraphs = $automaticNumberingCount
                numbered_structural_paragraphs = $numberedStructuralCount
                style_class_counts = $styleCounts
                outline_level_counts = $outlineCounts
                list_type_counts = $listTypeCounts
                prefix_pattern_counts = $prefixCounts
                paragraph_records = $records
                body_text_persisted = $false
            })
            $doc.Close(0)
            $doc = $null
        } catch {
            if ($null -ne $doc) {
                try { $doc.Close(0) } catch { }
                $doc = $null
            }
            $documentResults.Add([ordered]@{
                document_id = $documentId
                validation_status = 'failed'
                failure_type = $_.Exception.GetType().Name
                failure_message_redacted = $true
                body_text_persisted = $false
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
    inspection_mode = 'word_com_read_only_staged_hash_identical_copy'
    online_services_used = $false
    macros_executed = $false
    document_count = $documentResults.Count
    documents = $documentResults
}
Write-JsonAtomic $outputFull $payload

$summary = @($documentResults | ForEach-Object {
    [ordered]@{
        document_id = $_.document_id
        paragraphs = $_.nonempty_paragraph_count
        heading_style = $_.heading_style_paragraphs
        outline = $_.outline_level_paragraphs
        automatic_numbering = $_.automatic_numbering_paragraphs
        tables = $_.table_count
        toc = $_.toc_count
    }
})
$summary | ConvertTo-Json -Compress
