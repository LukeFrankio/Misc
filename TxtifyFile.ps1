<#
.SYNOPSIS
    Appends .txt to the extension of a file; batches multi-select renames.

.DESCRIPTION
    Called by the Txtify context menu registry entry (Txtify.reg).

    Windows Explorer spawns one process per selected file. This script uses
    a two-phase coordinator pattern that is correct under all timing conditions:

    PHASE 1 — Registration
      Every instance writes its target path to a per-PID file in a shared
      temp directory. No file locking needed; PIDs are unique per process.

    PHASE 2 — Coordination
      All instances race for a named mutex via non-blocking WaitOne(0).

      Coordinator (first to win):
        - Runs an adaptive stability loop: polls the queue every 50 ms,
          resets a timer whenever a new entry appears, and proceeds only
          after 200 ms of no new arrivals (capped at 5 s). This handles
          Windows Explorer spawning processes in staggered batches.
        - Reads all queued paths, deletes all entries, renames every file.
        - Releases the mutex.

      Non-coordinators (everyone else):
        - Block on WaitOne(10 000 ms) — waiting for the coordinator to
          finish. Blocked threads consume no CPU; they are parked by the OS.
        - After the mutex is released, each non-coordinator checks whether
          its own .entry file was deleted by the coordinator.
          * Already deleted  coordinator handled it; exit cleanly.
          * Still present    coordinator missed it (late arrival); rename it
                             now and delete the entry.
        - Release the mutex so the next non-coordinator can proceed.

    Net result: zero missed files under all timing conditions. N processes
    are still spawned (unavoidable without a compiled COM DropTarget handler),
    but the coordinator does the bulk rename and non-coordinators self-correct
    if they were late arrivals.

    Examples:
      test.md       ->  test.md.txt
      archive.zip   ->  archive.zip.txt
      script.sh     ->  script.sh.txt
      image.png     ->  image.png.txt

    On success the rename is silent.
    On failure a MessageBox lists every path that could not be renamed.

.PARAMETER FilePath
    Full path of the file passed by the shell via %1 in the registry command.

.EXAMPLE
    .\TxtifyFile.ps1 -FilePath "C:\Desktop\test.md"
#>

#Requires -Version 7.5

param(
    [Parameter(Mandatory)]
    [string]$FilePath
)

Add-Type -AssemblyName System.Windows.Forms

# ---------------------------------------------------------------------------
# Helper: rename a list of paths and report failures via MessageBox.
# ---------------------------------------------------------------------------

function Invoke-Renames {
    param([System.Collections.Generic.List[string]]$Paths)
    $errs = [System.Collections.Generic.List[string]]::new()
    foreach ($p in $Paths) {
        if ([string]::IsNullOrWhiteSpace($p)) { continue }
        if (-not (Test-Path -LiteralPath $p)) { continue }   # already renamed; skip silently
        $newName = [System.IO.Path]::GetFileName($p) + '.txt'
        try {
            Rename-Item -LiteralPath $p -NewName $newName -ErrorAction Stop
        } catch {
            $errs.Add("$p`n  $_")
        }
    }
    if ($errs.Count -gt 0) {
        $msg = "Could not rename the following file(s):`n`n" + ($errs -join "`n`n")
        [System.Windows.Forms.MessageBox]::Show($msg, 'Txtify', 0, 16) | Out-Null
    }
}

# ---------------------------------------------------------------------------
# Phase 1: register this file in the shared queue directory.
# ---------------------------------------------------------------------------

$queueDir = Join-Path $env:TEMP "txtify_$env:USERNAME"
$null     = New-Item -ItemType Directory -Force -Path $queueDir

$entry = Join-Path $queueDir "$PID.entry"
[System.IO.File]::WriteAllText($entry, $FilePath, [System.Text.Encoding]::UTF8)

# ---------------------------------------------------------------------------
# Phase 2: coordinate via named mutex.
# $holdsMutex tracks whether THIS process currently owns the mutex,
# so the finally block knows whether to call ReleaseMutex().
# ---------------------------------------------------------------------------

$mutex      = New-Object System.Threading.Mutex($false, "Global\Txtify_$env:USERNAME")
$holdsMutex = $mutex.WaitOne(0)   # non-blocking: true = we are the coordinator

try {
    if ($holdsMutex) {
        # -------------------------------------------------------------------
        # COORDINATOR PATH
        # Adaptive stability wait: keep polling until no new entries for
        # 200 ms, then drain the queue and rename everything.
        # -------------------------------------------------------------------

        $lastCount = 0; $stableMs = 0; $totalMs = 0
        $pollMs     = 50
        $stableGoal = 200    # ms of stability required before proceeding
        $maxMs      = 5000   # hard cap

        while ($stableMs -lt $stableGoal -and $totalMs -lt $maxMs) {
            Start-Sleep -Milliseconds $pollMs
            $totalMs += $pollMs
            $count = (Get-ChildItem -LiteralPath $queueDir -Filter '*.entry' `
                        -ErrorAction SilentlyContinue | Measure-Object).Count
            if ($count -gt $lastCount) { $lastCount = $count; $stableMs = 0 }
            else                        { $stableMs += $pollMs }
        }

        # Drain the queue
        $paths = [System.Collections.Generic.List[string]]::new()
        foreach ($f in (Get-ChildItem -LiteralPath $queueDir -Filter '*.entry' `
                            -ErrorAction SilentlyContinue)) {
            try {
                $line = [System.IO.File]::ReadAllText($f.FullName, [System.Text.Encoding]::UTF8).Trim()
                if ($line) { $paths.Add($line) }
                Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
            } catch {}
        }
        # Delete($path, $false) = non-recursive: throws IOException if non-empty,
        # never opens a UI prompt. Late-arriving entries survive and are handled
        # by their own non-coordinator self-correction pass.
        try { [System.IO.Directory]::Delete($queueDir, $false) } catch {}

        Invoke-Renames -Paths $paths

    } else {
        # -------------------------------------------------------------------
        # NON-COORDINATOR PATH
        # Block until the coordinator releases the mutex (up to 10 s).
        # Then check whether our own entry was processed; self-correct if not.
        # -------------------------------------------------------------------

        $holdsMutex = $mutex.WaitOne(10000)   # park this thread; no CPU used

        $paths = [System.Collections.Generic.List[string]]::new()

        if (-not $holdsMutex) {
            # Coordinator stalled or crashed. Rename our own file directly.
            $paths.Add($FilePath)
            try { Remove-Item -LiteralPath $entry -Force -ErrorAction SilentlyContinue } catch {}
        } else {
            # Coordinator finished. Was our entry file deleted (i.e. processed)?
            if (Test-Path $entry) {
                # Coordinator missed us — self-correct.
                try {
                    $line = [System.IO.File]::ReadAllText($entry, [System.Text.Encoding]::UTF8).Trim()
                    if ($line) { $paths.Add($line) }
                    Remove-Item -LiteralPath $entry -Force -ErrorAction SilentlyContinue
                } catch {}
            }
            # else: coordinator already handled our file — nothing to do
        }

        if ($paths.Count -gt 0) { Invoke-Renames -Paths $paths }
        try { [System.IO.Directory]::Delete($queueDir, $false) } catch {}
    }

} catch {
    # Unexpected exception — swallow; errors are reported via MessageBox in Invoke-Renames
} finally {
    try { if ($holdsMutex) { $mutex.ReleaseMutex() } } catch {}
    $mutex.Dispose()
}
