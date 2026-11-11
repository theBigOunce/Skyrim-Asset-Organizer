# Skyrim Asset Organizer — first test build

MO2-style selection UI and a loose NIF/DDS conflict planner, with selected-only cleanup, combining, and log-only manual recovery. This is an early test build: live MO2 supports **preview only**. Deletion is restricted to generated disposable testbeds. BOSSE PBR is not changed or used by the demo.

## Try the GUI safely

Double-click **Run Demo.cmd** in this project. The local Python/PyQt6 environment has been prepared on this machine. Each launch creates a fresh folder under `testbeds/`, containing synthetic mod folders, metadata, a profile, and matching ZIP downloads. These assets are placeholder bytes for file-operation testing, not valid game assets to install or launch in Skyrim.

1. Expand Visuals → Landscape, then tick Landscape to select its three mods. Untick individual mods to exclude them. Enabled status comes from the synthetic profile and is separate from your operation checkboxes.
2. Click Scan / Preview. Look for lower-priority copies of `textures/landscape/rock.dds` and `meshes/landscape/rock.nif`.
3. Enable combining and enter a new output name. Enable source removal if desired, then scan again.
4. Apply only to the disposable testbed. Inspect its `mods/`, `logs/*.jsonl`, and readable `logs/*.txt` files.
5. Close/reopen the demo for a fresh sample. Previous samples and their logs remain available for inspection.

Architecture also contains a file called rock.dds in a different directory. It must survive independently of the landscape rock.dds. A disabled alternative must never justify deletion. INIs are retained. No deleted-byte backups or recycle-bin copies are made.

For manual recovery, use the matching synthetic ZIP under `downloads/`, put the member back at the original mod-relative path, and compare SHA-256. Schema-2 JSONL records store mod and asset details once, then reference them by ID. The text file is a small summary. Search or export readable recovery records without opening the entire log in an editor:

```powershell
.\.venv\Scripts\python.exe log_report.py "testbeds\SAMPLE\logs\RUN.jsonl" --mod "Landscape Base" --contains rock --limit 100
```

Completed events establish outcomes; an interrupted batch can contain uncertain actions. Inspect those paths before manually recovering anything. The viewer supports schema 2; the initial build's schema-1 logs remain ordinary JSONL with their full embedded plan.

## Terminal demo and tests

```powershell
.\.venv\Scripts\python.exe demo.py --cli
.\.venv\Scripts\python.exe demo.py --cli --apply
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Both CLI demo commands create new testbeds; `--apply` changes only that newly created sample. To revisit an existing fixture, use `--root <absolute project/testbeds/sample path>`.

On another machine, create a Python 3.11+ virtual environment named `.venv`, then install `requirements-demo.txt`. MO2 supplies its own Python/PyQt6 runtime for plugins; never copy this virtual environment into MO2.

## MO2 plugin preview

The plugin package is `plugin/SkyrimAssetOrganizer/`. Copy that whole folder into a disposable MO2 instance's `plugins/` directory and restart MO2. Open Skyrim Asset Organizer from the tools menu. Its live instance adapter is read-only; Apply is disabled. The first release has not yet been verified inside MO2 itself, so use the standalone fixture demo first. Do not deploy to BOSSE for destructive use.

An equivalent source-only ZIP is provided under `dist/SkyrimAssetOrganizer-preview-0.2.0.zip`; extract it into the disposable instance's `plugins/` directory. Rebuild it with `.venv\Scripts\python.exe package_plugin.py`. Plugin methods follow the [official MO2 Python API](https://www.modorganizer.org/python-plugins-doc/autoapi/mobase/index.html); actual in-MO2 loading remains unverified in this test build.

Actual conflict identity is the full relative Data path, compared case-insensitively. Combining retains that full nested structure. Priority and enabled status come exclusively from the selected profile; only selected enabled sources participate in cleanup. Other profiles share the physical asset removals when live writes are eventually enabled.

## Current limits

The scanner indexes loose `.nif` and `.dds` paths under `meshes/` and `textures/` in a temporary SQLite database. It excludes archives, hidden files, disabled mods and non-asset content. Preview reads metadata only; Apply captures source/winner hashes before writing the complete recovery manifest, then verifies touched bytes before mutation. Unrelated files require metadata only. Scanning runs in a background thread with progress and cancellation. The preview fetches rows on demand rather than creating widgets for every action. Closing/cancelling a scan waits for safe worker termination.

Combining calculates insertion bounds per selected path, rather than simulating the whole list at every priority. It conservatively preserves provider identity, so it may reject a merge that could work if different providers happen to contain identical bytes. Live MO2 mutation, archive-member discovery, a graphical history browser, and background/cancellable apply remain future work. **Apply is still synchronous and fixture-only.** Preview exposes source metadata and candidate downloads; archive-member attribution is not assumed. Unknown or modified/generated assets may not be manually recoverable from downloads.

Plans are temporary disk indexes under `.sao-cache/`, normally removed when closed. Interrupted processes can leave indexes behind. These contain paths/hashes/metadata, never backup copies of assets. Durable operation logs stay in the sample's `logs/` directory. Each batch of up to 128 actions has its intent flushed before mutation; completion events flush at batch boundaries. This reduces log flush overhead while honestly retaining uncertainty after interruption. Explicit full preview export can still be large and runs synchronously; use filtered recovery exports for everyday reading.

Copies are verified before any source removal, and complete per-file intent/provenance is flushed to disk before deleting. Failures stop further actions and remain in the log; already removed assets have no automatic rollback. Keep the generated downloads for the demo recovery exercise.

See IMPLEMENTATION_PLAN.md for the broader design; this test build implements a subset.

## Scaling benchmark

`benchmark_scale.py` creates a disposable sample with 3,000 mod folders and 300,000 real tiny files by default, then measures scan/planning, process peak working set, temporary index size, and normalized plan-log size. It does not apply or create a 400 GB payload. Run it only when you want this many disposable files; they remain under `testbeds/scale-*` for inspection. See PERFORMANCE.md for recorded results and limitations.
