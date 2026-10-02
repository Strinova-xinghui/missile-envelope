#requires -Version 5.1
<#
.SYNOPSIS
  One-shot GitHub publisher for the 导弹包线图 OSS branch (Route A from docs/OPENSOURCE-READINESS.md).

.DESCRIPTION
  Builds a PUBLIC-SAFE snapshot from `git archive HEAD` in a throwaway temp dir, so the shared
  3-worktree object store is never modified. Then applies the "do not publish" exclusion set,
  optionally writes a real LICENSE, runs the mandatory pre-push gate (docs/OPENSOURCE-READINESS.md
  section 4.6) and only pushes when EVERY check passes.

  Safety properties:
    * read-only against the source repo (git archive only) - other worktrees cannot be disturbed
    * never pushes --all / --mirror (that would leak vendor history from sibling branches)
    * refuses PUBLIC visibility unless a real license body was installed
    * refuses to push if any gate fails; exits non-zero with the failing reason

.LINK
  docs/OPENSOURCE-READINESS.md  (section 4.3 Route A, section 4.6 gate, section 5 license)
#>
[CmdletBinding()]
param(
    # Where the repo is published. Private is the documented default: fix the gate on a private
    # repo first, flip to public later with one click.
    [ValidateSet('Private', 'Public')]
    [string] $Visibility = 'Private',

    # 'None' keeps the existing PLACEHOLDER LICENSE. A Public release is refused in that case.
    [ValidateSet('None', 'MIT', 'Apache-2.0', 'GPL-3.0')]
    [string] $License = 'None',

    # Remote repository name (GitHub slug) and human-readable title.
    [string] $RepoName = 'missile-sim',
    [string] $RepoDesc = 'Missile flight-path envelope charts (community research, War Thunder data)',

    # Commit author. Needed because global git identity is often unset on this machine;
    # we only ever set it LOCALLY inside the temp snapshot, never globally.
    [string] $AuthorName,
    [string] $AuthorEmail,

    # Stop after the gate: build snapshot + commit + verify, but do not create/push the repo.
    [switch] $DryRun,

    # Keep the temp snapshot for manual inspection instead of deleting it.
    [switch] $Keep,

    # Skip the 50-test kernel-free run (slow-ish); the structural gates still run.
    [switch] $SkipTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
function Say([string] $m) { Write-Host $m }
function Head([string] $m) { Write-Host ''; Write-Host "== $m ==" }

# Gate bookkeeping: name / expected / observed / pass
$script:gates = New-Object System.Collections.ArrayList
function Gate([string] $name, [string] $expect, $observed, [bool] $ok) {
    [void] $script:gates.Add([pscustomobject]@{
        Name = $name; Expect = $expect; Observed = "$observed"; Pass = $ok
    })
    $tag = if ($ok) { 'PASS' } else { 'FAIL' }
    Say ("  [{0}] {1}  (expect {2} | got {3})" -f $tag, $name, $expect, $observed)
}

function RunGit(array $args, [string] $cwd) {
    # Captures stdout as strings; throws on non-zero exit so a broken step never looks "green".
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & git -C $cwd @args 2>&1
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $prev }
    if ($code -ne 0) {
        throw "git $($args -join ' ') failed (exit $code): $($out -join ' | ')"
    }
    , @($out | ForEach-Object { "$_" })
}

# ---------------------------------------------------------------------------
# 0. locate source repo + confirm it is the OSS worktree
# ---------------------------------------------------------------------------
Head 'step 0  preconditions'

$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RepoRoot '.git'))) {
    throw "not a git worktree: $RepoRoot (run this script from the OSS checkout)"
}
Say "  source worktree : $RepoRoot"

$branch = (RunGit @('rev-parse', '--abbrev-ref', 'HEAD') $RepoRoot)[0]
Say "  source branch   : $branch"

$dirty = RunGit @('status', '--porcelain=v1') $RepoRoot
if ($dirty.Count -gt 0) {
    Say "  dirty files     : $($dirty.Count)"
    $dirty | Select-Object -First 10 | ForEach-Object { Say "                    $_" }
    throw 'working tree is not clean: commit or stash first, so the published snapshot matches a real commit'
}

foreach ($tool in 'git', 'python') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool not on PATH" }
}

# ---------------------------------------------------------------------------
# 1. export HEAD to a throwaway tree (READ-ONLY against the shared object store)
# ---------------------------------------------------------------------------
Head 'step 1  export snapshot (git archive, source repo untouched)'

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Work  = Join-Path $env:TEMP "dsh-publish-oss-$stamp"
New-Item -ItemType Directory -Path $Work -Force | Out-Null
$Zip   = Join-Path $Work 'snapshot.zip'
$Snap  = Join-Path $Work 'snap'

RunGit @('archive', "--format=zip", '--prefix=snap/', "-o$Zip", 'HEAD') $RepoRoot | Out-Null
Expand-Archive -Path $Zip -DestinationPath $Work -Force
Say "  exported to     : $Snap"

$zipMB = [math]::Round((Get-Item $Zip).Length / 1MB, 2)
Say "  archive size    : $zipMB MB"

# ---------------------------------------------------------------------------
# 2. apply the documented "do not publish" exclusion set
# ---------------------------------------------------------------------------
Head 'step 2  remove non-public set (section 4.3)'

# NOTE: kept as forward-slash repo-relative paths so the list is diff-able against the doc.
$Exclude = @(
    'vendor/wt-missile/wt_missile.py',   # third-party solver, no license statement
    'vendor/wt-missile/inputs',          # 168 War Thunder .blk game data files
    'vendor/wt-missile/example.json',
    'vendor/wt-missile/README.txt',
    'archive/figures-legacy',            # 23 unreproducible early figures
    'results/reference_fig.png',         # third-party image, authorization unconfirmed
    'results/pro_cache.json',            # deleted `pro` architecture leftover
    'results/runs'                       # deleted-architecture scan output
)
# Deliberately KEPT: vendor/wt-missile/VENDOR.md and vendor/README.md (our own docs, public-safe).

$removedCount = 0
foreach ($rel in $Exclude) {
    $p = Join-Path $Snap ($rel -replace '/', [IO.Path]::DirectorySeparatorChar)
    if (Test-Path -LiteralPath $p) {
        $n = if (Test-Path -LiteralPath $p -PathType Container) {
            (Get-ChildItem -LiteralPath $p -Recurse -File -Force).Count
        } else { 1 }
        Remove-Item -LiteralPath $p -Recurse -Force
        $removedCount += $n
        Say ("  removed  {0,-38} ({1} files)" -f $rel, $n)
    } else {
        Say ("  absent   {0}  (already gone - fine)" -f $rel)
    }
}
Say "  total removed   : $removedCount files"

# ---------------------------------------------------------------------------
# 3. scrub local absolute paths (section 7 items 9/10) - temp copy only
# ---------------------------------------------------------------------------
Head 'step 3  scrub local machine paths'

# Only C:\Users\<name> and D:\Download leak the owner's environment. `E:\WT` references are
# documented as intentional (CONTRIBUTING.md section 5) and are NOT rewritten - do not "fix" them.
$ScrubPattern = 'C:\\+Users\\+[A-Za-z0-9._-]+(?:\\+[^"'']*?)?'
$scrubbed = New-Object System.Collections.ArrayList
$targets = Get-ChildItem -LiteralPath $Snap -Recurse -File -Force -Include '*.json', '*.md', '*.txt', '*.py'
foreach ($f in $targets) {
    $bytes = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    if (-not $bytes) { continue }
    if ($bytes -notmatch 'C:\\+Users\\' -and $bytes -notmatch 'D:\\+Download\\') { continue }
    $new = [regex]::Replace($bytes, $ScrubPattern, '<LOCAL_CACHE_PATH>')
    $new = [regex]::Replace($new, 'D:\\+Download\\+', '<LOCAL_DOWNLOAD_PATH>/')
    if ($new -ne $bytes) {
        # ASCII-8 in UTF8 no-BOM keeps these data files byte-stable for the JSON they encode.
        [IO.File]::WriteAllText($f.FullName, $new, (New-Object Text.UTF8Encoding($false)))
        [void] $scrubbed.Add($f.FullName.Substring($Snap.Length + 1))
    }
}
if ($scrubbed.Count -eq 0) { Say '  nothing to scrub' }
else { $scrubbed | ForEach-Object { Say "  scrubbed $_" } }

# ---------------------------------------------------------------------------
# 4. license body (section 5) - fetched from GitHub's official SPDX templates
# ---------------------------------------------------------------------------
Head 'step 4  license'

$LicPath = Join-Path $Snap 'LICENSE'
if ($License -eq 'None') {
    Say "  LICENSE kept as-is (PLACEHOLDER). Visibility '$Visibility'."
} else {
    $year = (Get-Date).Year
    # Author for the copyright line: explicit param > global git identity > gh login.
    if (-not $AuthorName) { $AuthorName = (git config --global user.name) }
    if (-not $AuthorName) {
        if (Get-Command gh -ErrorAction SilentlyContinue) {
            try { $AuthorName = (gh api user -jq .login) } catch { }
        }
    }
    if (-not $AuthorName) { throw 'cannot determine copyright holder: pass -AuthorName' }
    Say "  fetching official $License text from api.github.com"
    $api = Invoke-RestMethod -Uri "https://api.github.com/licenses/$License" -Headers @{
        'Accept' = 'application/vnd.github+json'; 'User-Agent' = 'dsh-publish-github'
    }
    $body = $api.body -replace '\[year\]', $year -replace '\[fullname\]', $AuthorName
    [IO.File]::WriteAllText($LicPath, $body.TrimEnd() + "`n", (New-Object Text.UTF8Encoding($false)))
    Say ("  wrote LICENSE  : {0} ({1})" -f $api.name, $api.license_id)

    # Keep pyproject metadata consistent with the LICENSE file (CONTRIBUTING requires no drift).
    $py = Join-Path $Snap 'pyproject.toml'
    $pyText = Get-Content -LiteralPath $py -Raw -Encoding UTF8
    if ($pyText -match '(?m)^\s*license\s*=') {
        Say '  pyproject.toml already declares license - left untouched'
    } else {
        $spdx = switch ($License) {
            'Apache-2.0' { 'Apache-2.0' }
            'GPL-3.0'    { 'GPL-3.0-only' }
            default      { 'MIT' }
        }
        # Insert exactly once, right after the readme line inside [project]. The table form
        # `license = { text = ... }` is what setuptools>=68 understands; the bare-string form
        # (PEP 639) needs setuptools>=77, which pyproject's own pin does not guarantee.
        $newText = $pyText -replace '(?m)^(readme\s*=\s*"[^"]*"[^\r\n]*)$', "`$1`nlicense = { text = `"$spdx`" }"
        if ($newText -eq $pyText) { throw 'could not insert license: no readme line found in [project]' }
        if ([regex]::Matches($newText, '(?m)^\s*license\s*=').Count -ne 1) {
            throw 'license insertion produced more than one license key'
        }
        # Deliberately NOT touching classifiers: PyPI's license classifiers use the spaced form
        # ("License :: OSI Approved :: MIT License"), which does not map mechanically onto the
        # SPDX id we just wrote, and a wrong classifier is worse than none. Do it by hand.
        [IO.File]::WriteAllText($py, $newText, (New-Object Text.UTF8Encoding($false)))
        Say "  pyproject.toml license field set to $spdx"
    }
}

# ---------------------------------------------------------------------------
# 5. init fresh repo + single initial commit (local identity only)
# ---------------------------------------------------------------------------
Head 'step 5  fresh repository + single commit'

RunGit @('init', '-b', 'main') $Snap | Out-Null

# Resolve author/email locally (never --global).
if (-not $AuthorName)      { $AuthorName  = (git config --global user.name) }
if (-not $AuthorEmail)     { $AuthorEmail = (git config --global user.email) }
if (-not $AuthorName -or -not $AuthorEmail) {
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        try {
            $u = gh api user | ConvertFrom-Json
            if (-not $AuthorName)  { $AuthorName  = $u.login }
            if (-not $AuthorEmail) { $AuthorEmail = "$($u.id)+$($u.login)@users.noreply.github.com" }
        } catch { }
    }
}
if (-not $AuthorName -or -not $AuthorEmail) {
    throw 'cannot determine commit author: pass -AuthorName and -AuthorEmail, or set git global identity, or log in with gh'
}
Say "  author          : $AuthorName <$AuthorEmail>"

# Line endings: the repo documents that mixed CRLF/LF is intentional (.gitattributes `* -text`).
# Never enable autocrlf here - it would rewrite AGENTS.md and every results/*.json.
RunGit @('config', 'core.autocrlf', 'false') $Snap | Out-Null
RunGit @('config', 'user.name', $AuthorName) $Snap | Out-Null
RunGit @('config', 'user.email', $AuthorEmail) $Snap | Out-Null

RunGit @('add', '-A') $Snap | Out-Null
$msg = @('Initial public release: missile flight-path envelope tooling.',
         '',
         'Shell + reproducible artifacts only. The third-party solver kernel and',
         'War Thunder game data (vendor/wt-missile/**) are NOT included - see',
         'vendor/README.md for how to supply them locally.') -join "`n"
RunGit @('commit', '-q', '-m', $msg) $Snap | Out-Null
Say '  committed'

# ---------------------------------------------------------------------------
# 6. THE GATE - section 4.6. Any FAIL blocks the push.
# ---------------------------------------------------------------------------
Head 'step 6  pre-push gate (docs/OPENSOURCE-READINESS.md section 4.6)'

$ErrorActionPreference = 'Continue'

# G1/G2: history must not contain game data or kernel sources.
$allObjects = RunGit @('rev-list', '--objects', '--all') $Snap
$blkHist   = @($allObjects | Where-Object { $_ -match '\.(blk|blkx|vromfs)(\s|$)' })
$kernHist  = @($allObjects | Where-Object { $_ -match 'wt_missile\.py|vendor/wt-missile/inputs' })
Gate 'G1 history has no game data'      '0' $blkHist.Count   ($blkHist.Count   -eq 0)
Gate 'G2 history has no kernel source' '0' $kernHist.Count  ($kernHist.Count  -eq 0)

# G3: filter-branch backup refs must be absent (route A never creates them, assert anyway).
$origRefs = RunGit @('for-each-ref', '--format=%(refname)', 'refs/original') $Snap
Gate 'G3 no refs/original backup' 'empty' $origRefs.Count ($origRefs.Count -eq 0)

# G4: tracked working tree clean of kernel/game data.
$tracked = RunGit @('ls-files') $Snap
$badTrack  = @($tracked | Where-Object { $_ -match '\.(blk|blkx|vromfs)$|wt_missile\.py$|^vendor/wt-missile/inputs/' })
Gate 'G4 tree free of kernel/data' '0' $badTrack.Count ($badTrack.Count -eq 0)

# G5: exactly one commit.
$commitCount = (RunGit @('rev-list', '--count', 'HEAD') $Snap)[0]
Gate 'G5 single initial commit' '1' $commitCount ([int] $commitCount -eq 1)

# G6: no remote yet (we add it explicitly right before push).
$remotes = RunGit @('remote') $Snap
Gate 'G6 no pre-existing remote' 'empty' $remotes.Count ($remotes.Count -eq 0)

# G7: only the intended vendor docs survived.
$vendorKept = @($tracked | Where-Object { $_ -like 'vendor/*' })
$unexpected = @($vendorKept | Where-Object { $_ -notin 'vendor/README.md', 'vendor/wt-missile/VENDOR.md' })
Gate 'G7 vendor keeps only our docs' '2 files' "$($vendorKept.Count) [$($vendorKept -join ', ')]" ($unexpected.Count -eq 0)

# G8: no leaked local paths.
$leak = @(); foreach ($t in $tracked) {
    $fp = Join-Path $Snap ($t -replace '/', [IO.Path]::DirectorySeparatorChar)
    if (-not (Test-Path -LiteralPath $fp -PathType Leaf)) { continue }
    if ($t -notmatch '\.(json|md|txt|py|toml|yml|yaml)$') { continue }
    $c = Get-Content -LiteralPath $fp -Raw -ErrorAction SilentlyContinue
    if ($c -and ($c -match 'C:\\+Users\\+[A-Za-z0-9._-]+' -or $c -match 'D:\\+Download\\+')) { $leak += $t }
}
Gate 'G8 no local absolute paths' '0' "$($leak.Count) [$($leak -join ', ')]" ($leak.Count -eq 0)

# G9: secrets.
$secret = @(); foreach ($t in $tracked) {
    $fp = Join-Path $Snap ($t -replace '/', [IO.Path]::DirectorySeparatorChar)
    if (-not (Test-Path -LiteralPath $fp -PathType Leaf)) { continue }
    if ($t -match '\.(png|jpg|jpeg|gif|pdf|zip|whl|pyc|xlsx)$') { continue }
    $c = Get-Content -LiteralPath $fp -Raw -ErrorAction SilentlyContinue
    if ($c -and $c -match '(?i)(api[_-]?key\s*[=:]|secret[_-]?key\s*[=:]|password\s*[=:]|BEGIN\s+[A-Z ]*PRIVATE KEY|github_pat_|ghp_[A-Za-z0-9]{20,})') { $secret += $t }
}
Gate 'G9 no secrets' '0' "$($secret.Count) [$($secret -join ', ')]" ($secret.Count -eq 0)

# G10: GitHub hard 100 MB per-file limit (warning at 50 MB).
$big = @(Get-ChildItem -LiteralPath $Snap -Recurse -File -Force | Where-Object { $_.Length -gt 50MB })
Gate 'G10 no file > 50 MB' '0' "$($big.Count) [$(($big | ForEach-Object { $_.Name }) -join ', ')]" ($big.Count -eq 0)

# G11: LICENSE must be a real body before going public.
$licOk = $true; $licInfo = "License=$License"
if ($Visibility -eq 'Public') {
    $licTxt = if (Test-Path -LiteralPath $LicPath) { Get-Content -LiteralPath $LicPath -Raw } else { '' }
    $isPlaceholder = $licTxt -match 'PLACEHOLDER|这不是许可证|not a license'
    $longEnough = $licTxt.Length -gt 1000
    $licOk = (-not $isPlaceholder) -and $longEnough
    $licInfo = "placeholder=$isPlaceholder len=$($licTxt.Length)"
}
Gate 'G11 license installed for public' 'real text' $licInfo $licOk

# G12: kernel-free tests green (37 + 12 + 1).
if ($SkipTests) {
    Gate 'G12 kernel-free tests' 'skipped' '-SkipTests' $true
} else {
    $expected = @{ flightpath = 37; form_dirty = 12; printed_text = 1 }
    $tally = @(); $allGreen = $true
    Push-Location $Snap
    try {
        $env:PYTHONUTF8 = '1'; $env:PYTHONPATH = 'src'
        foreach ($k in $expected.Keys) {
            $o = & python tests/run_tests.py "-k" $k 2>&1
            $line = ($o | Select-String -Pattern '通过.*失败.*共' | Select-Object -Last 1)
            if ($line -match '通过\s*(\d+)\s*/\s*失败\s*(\d+)\s*/\s*共\s*(\d+)') {
                $p = [int] $Matches[1]; $f = [int] $Matches[2]
                $tally += "${k}:${p}pass/${f}fail"
                if ($f -ne 0 -or $p -ne $expected[$k]) { $allGreen = $false }
            } else { $tally += "${k}:NO-RESULT"; $allGreen = $false }
        }
    } finally { Pop-Location }
    Gate 'G12 kernel-free tests green' '37/12/1, 0 fail' ($tally -join ' ') $allGreen
}

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# 7. report + push
# ---------------------------------------------------------------------------
Head 'gate summary'
$failed = @($script:gates | Where-Object { -not $_.Pass })
foreach ($g in $script:gates) {
    Say ("  {0,-34} {1,-9} expect={2}  got={3}" -f $g.Name, ($(if ($g.Pass) { 'PASS' } else { 'FAIL' })), $g.Expect, $g.Observed)
}

$trackedMB = [math]::Round(((Get-ChildItem -LiteralPath $Snap -Recurse -File -Force | Where-Object { $tracked -contains (($_.FullName.Substring($Snap.Length + 1)) -replace [IO.Path]::DirectorySeparatorChar, '/') } | Measure-Object Length -Sum).Sum) / 1MB, 2)
Say "  tracked payload : $trackedMB MB / $($tracked.Count) files"
Say "  snapshot dir    : $Snap"

if ($failed.Count -gt 0) {
    Say ''
    Say ("  RESULT: BLOCKED - {0} gate(s) failed. Nothing was pushed." -f $failed.Count)
    if ($Keep) { Say "  snapshot kept for inspection: $Snap" }
    else { Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue }
    exit 1
}

Say ''
Say '  RESULT: all gates green.'

if ($DryRun) {
    Say '  DRY RUN: stopping before repository creation / push.'
    Say "  snapshot is ready at: $Snap"
    Say "  to publish for real, re-run without -DryRun (or push manually):"
    Say "      cd `"$Snap`""
    Say "      gh repo create $RepoName --private --source . --push"
    exit 0
}

# Push path: gh is the only supported way to create the remote from here.
$visFlag = if ($Visibility -eq 'Public') { '--public' } else { '--private' }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Say "  GitHub CLI (gh) is not installed - refusing to guess a remote."
    Say '  Install it:   winget install -e --id GitHub.cli'
    Say '  Then log in:  gh auth login   (browser flow; your credentials stay yours)'
    Say "  Or push manually from the snapshot:"
    Say "      cd `"$Snap`""
    Say "      git push -u origin main        # main ONLY - never --all or --mirror"
    exit 2
}
$authed = $false
$prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& gh auth status 2>&1 | Out-Null; if ($LASTEXITCODE -eq 0) { $authed = $true }
$ErrorActionPreference = $prevEAP
if (-not $authed) {
    Say '  gh is installed but not authenticated. Run: gh auth login'
    Say "  snapshot ready at: $Snap"
    exit 2
}

Head 'step 7  create repository and push'
Push-Location $Snap
try {
    # `--source . --push` creates the repo and pushes the CURRENT branch only.
    & gh repo create $RepoName $visFlag --description $RepoDesc --source . --push
    $code = $LASTEXITCODE
} finally { Pop-Location }
if ($code -ne 0) { throw "gh repo create failed (exit $code)" }

$url = (RunGit @('config', '--get', 'remote.origin.url') $Snap)[0]
Say "  published : $url"
Say "  visibility: $Visibility"
Say '  next      : check Actions (ci.yml runs the 50 kernel-free tests automatically)'

if (-not $Keep) { Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue }
else { Say "  snapshot kept at: $Snap" }
Say ''
Say 'DONE.'
