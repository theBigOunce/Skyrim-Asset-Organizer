# Performance pass — 2026-11-11

Initial build: `90fee39`. Optimized implementation: `a0ee467`, with benchmark/report refinements in the following commit. Live MO2 mutation remains disabled.

## Measured workload

Windows, Python 3.12, project on S:. A generated fixture contains 3,000 enabled mod directories, 300,000 real tiny DDS files, and approximately 24,000 asset directories (textures/landscape plus six subdirectories per mod). Each mod contains the same 100 relative asset paths with differing placeholder content. All mods were selected, with combining and copied-source removal planned. This yields 300,100 planned actions. No asset files were deleted or combined by this benchmark.

The measured run reused the already-created fixture. OS filesystem caches were warm from earlier runs; fixture generation is excluded. This measures path indexing, planning, memory, and log structure, not cold-drive throughput or a 400 GB payload.

| Measurement | Result |
|---|---:|
| Preview scan and planning | 96.78 seconds |
| Peak process working set, scanner CLI | 36.00 MiB |
| Temporary SQLite plan index | 367.08 MiB |
| Asset-content bytes hashed/read by preview | 0 |
| Generated preview-plan log, hashes unset | 101.49 MiB |
| Writing that preview-plan log | 5.28 seconds |
| Modeled plan log with full 64-character hashes | 118.65 MiB |
| Search/index the preview-plan log, return one matching record | 3.17 seconds |
| Peak process working set for that log search | 26.35 MiB |

The modeled log size was calculated by serializing the actual generated records with placeholder 64-character hashes, not by reading asset contents. Full execution logs additionally contain completion, batch, and profile-publication events; roughly another few tens of MiB for this action count. This is not a measured 300,000-file destructive run. Path lengths and action mix change sizes. The text summary is small; filtered readable exports expand only the requested records.

The memory figures are Windows process peak working set, not a promise about total system RAM or OS filesystem caching. The scanner benchmark excludes the Qt GUI. The GUI verification separately attaches a virtual million-row action sequence and checks that model attachment reads zero rows and displaying one row fetches it once. It also tests cancellation, deferred closing, full-path selection, streaming export, and fixture apply.

## Changes

- Preview walks file metadata without opening asset contents. Original hashes are captured at Apply, before the complete recovery manifest is durably saved and before deletion. Touched files are verified again before use; unrelated files are never content-hashed.
- Inventories and action records live in temporary SQLite storage with bounded page cache and disk temporary sorting. Rows are fetched on demand. Mod provenance is shared per mod in memory.
- Preview scans run in a cancellable worker. The UI freezes operation controls during a scan, but continues processing events. Closing requests cancellation and waits for worker cleanup.
- Output placement uses insertion bounds per path, rather than rebuilding a full simulation for each mod priority. It conservatively preserves provider identity; identical bytes from different providers do not relax bounds.
- Normalized schema-2 logs store mod roots/metadata once and asset relative paths/hashes once. Actions reference IDs. There is no giant initial JSON line containing the whole plan.
- The complete plan is flushed before any mutation. Groups of up to 128 actions have durable batch intents before changes; completion events flush at batch boundaries. Missing completion records after interruption mean uncertain outcomes, not successful rollback.
- Temporary indexes disable SQLite rollback journaling and synchronous flushes. They can be discarded and rebuilt; they are never the recovery authority. The separate JSONL recovery journal retains explicit fsync barriers before mutations. Completed output copies and profile publication are also flushed.
- `log_report.py` reads the log into a temporary disk search index and prints only requested records, reconstructing full source/winner paths and metadata. It does not load the entire log into RAM or require a text editor to open a hundred-megabyte file.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe verify_demo_gui.py
.\.venv\Scripts\python.exe benchmark_scale.py
```

The benchmark creates a new 300,000-file sample under `testbeds/scale-*`; file metadata and indexes consume disk space even though file contents are tiny. Reuse an existing generated sample with `--existing testbeds\scale-SAMPLE`. It leaves the sample and measurement logs for inspection, and removes its normal temporary scan index on close. Interrupted earlier experiments can leave disposable `.sao-cache/` indexes. Generated samples, cache, environments, logs, ZIPs, and external reference-source trees are excluded from Git.

## Remaining limits

- A real combine still has to read, hash, copy, verify, and write the selected content. This benchmark does not establish transfer times, disk wear, free-space behavior, or power-loss durability for 400 GB. The optimization mainly removes those reads from preview and bounds planning memory.
- Apply remains synchronous and fixture-only; large fixture applies can freeze the GUI. Background apply, stronger live-instance coordination and broader live-MO2 verification are required before production deletion is enabled.
- Explicit full preview export remains synchronous and can be large; use filtered log exports for manual recovery.
- Directory access errors abort scanning rather than silently skipping providers. Fixture profile changes invalidate plans. Verified output activation is atomically published before removing source assets, with regression tests for publication failure.
- All 19 core tests and the GUI workflow checks pass. This is not a claim that every live MO2 mapping, archive, interruption or filesystem edge case has been certified.
