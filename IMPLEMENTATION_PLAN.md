# Skyrim Asset Organizer — implementation proposal

Status: implementation started on 2026-11-11 at the user's request. Confirmed: log-only manual recovery, conflicts between selected enabled mods only, and priority/enablement from the selected profile only. Physical deletions affect shared mod folders in every profile. The first test build permits writes only inside marked disposable testbeds; live MO2 remains preview-only. See README.md for implemented scope and launch instructions. BOSSE PBR has not been modified.

## Recommendation

Build an MO2 Python/PyQt6 tool plugin, with a separate, testable Python core for planning, provenance, and journaled file operations. Start with MO2 2.5.2 and Skyrim SE/AE. A standalone log viewer can reuse that core later; a standalone conflict scanner would need to reconstruct MO2's current state and is less suitable as the first UI.

Use MO2's public API rather than hooking TrueFolder's Qt model. Reconstruct the selection tree from separator names and actual profile priority. This avoids depending on TrueFolder's C++ internals. Capability-check the installed Python API at startup; the installed BOSSE Python bridge is not necessarily identical to a stock 2.5.2 distribution.

## Evidence reviewed

- `lostdragonistsmods/MO2-Plugins/src/ConflictDeleter/ConflictDeleter.py`: traverses the active virtual filesystem, obtains origins, and moves losing physical files to `ConflictDeleter_Backup_<timestamp>/<source mod>/<relative path>`. It processes the whole enabled list, has no extension filter, and provides no durable per-file transaction/restore interface. Its backup retains the disk space. The included source uses PyQt5; the installed BOSSE version uses PyQt6 and imports mobase explicitly.
- `lostdragonistsmods/MO2-Plugins/LICENSE`: MIT; retain attribution if reusing code.
- `mo2.5.2source/organizercore.cpp`, especially `getFileOrigins`, `findFileInfos`, `resolvePath`: the winning origin is emitted first; file information also identifies an archive-backed winner. An origin name alone does not establish whether an alternative is a loose file or archive member.
- `mo2.5.2source/modinforegular.cpp`: mod metadata includes version, installationFile, gameName, modid, repository, and an array of installed mod/file IDs. This is mod-level evidence, not guaranteed provenance for every file.
- `mo2.5.2source/downloadmanager.cpp`: download sidecars include gameName, modID, fileID, version, modName, and repository. Do not export signed download URLs or credentials.
- `mo2.5.2source/profile.cpp`: modlist.txt is stored in reverse priority order. Do not mistake its first entry for the lowest-priority mod.
- `truefolder2/src/folder_manager.h` and `override.cpp::ProxyModel::buildTree`: leading `#` count sets folder depth; folders attach to the nearest preceding shallower folder in ascending priority order. A normal separator does not reset the current TrueFolder container in this implementation. Support ordinary separator ranges separately and test mixed trees against this behavior. Account for actual separator flags and names ending in `_separator`, as found in BOSSE; do not assume all names use the helper's legacy `_separator_` prefix.
- `truefolder2/src/plugin.cpp`: this source explicitly checks for MO2 2.5.2 and installs internal hooks. Our independent selection tree does not need those hooks.
- BOSSE read-only inspection: ModOrganizer.exe reports 2.5.2; 11 profiles exist, and the saved selected profile is Quest Updates. Quest Updates contains 1,217 enabled entries. Mod folders are shared between profiles. Some local/generated mods have no download or Nexus ID. The user has chosen to evaluate only the selected profile and use manual recovery from logs.

Online references:

- [MO2 Python API](https://www.modorganizer.org/python-plugins-doc/autoapi/mobase/index.html): IPluginTool, IOrganizer, IModList, IProfile, FileInfo.
- [Official plugin guidance](https://github.com/ModOrganizer2/modorganizer/wiki/Writing-Mod-Organizer-Plugins): Python is supported and easier to start; its older embedded Python examples are explicitly marked outdated for 2.5.2.
- [MO2 2.5.2 release](https://github.com/ModOrganizer2/modorganizer/releases/tag/v2.5.2).
- [Conflict Deleter upstream](https://github.com/LostDragonist/MO2-Plugins).
- [TrueFolder II author page](https://www.nexusmods.com/skyrimspecialedition/mods/170925).
- [Cathedral Assets Optimizer upstream](https://github.com/Guekka/cathedral-assets-optimizer/).
- [Dragonborn's Fate LOD guide source](https://github.com/ModdingLinked/Dragonborns-Fate/blob/main/lod.html): documents loose-file precedence over BSA contents and an example of DDS data requiring loose files.

## Initial scope

Only physical loose `.nif` and `.dds` files, compared case-insensitively by relative game Data path. Offer independent meshes/textures switches. Initially default to assets under `meshes/` and `textures/`; report matching extensions elsewhere for explicit inclusion, rather than silently moving tool resources such as BodySlide templates.

Confirmed folder preservation: the conflict key is the complete relative path from each mod root, never the filename alone. For example, `Mod A/textures/landscape/rocks.dds` conflicts with `Mod B/textures/landscape/rocks.dds`, but not with `Mod B/textures/architecture/rocks.dds`. The source mod directory name is excluded from the key. Normalize path separators and Windows case for comparison without collapsing distinct directory paths.

Combining writes each retained asset at exactly the same relative path inside the output mod, preserving all nested folders (for example, `mods/Combined Landscapes/textures/landscape/rocks.dds`). Never flatten files or retain source mod names as extra directory levels. Logs include both the full original location and the full relative asset path. Fixture acceptance tests must cover identical basenames in different folders surviving cleanup and combining independently, and matching nested paths resolving by selected-mod priority.

Do not edit ESP/ESM/ESL, scripts, INIs, JSON/configuration, download archives, or BSA contents. Existing archives can be identified as context, but archive-backed or ambiguous cases must not authorize deletion in v1. Hidden `.mohidden` assets and disabled mods are excluded from destructive operations by default. Overwrite, unmanaged Data, official content, separators, and output mods from the current operation are never deletion targets.

This changes file conflicts; it does not infer whether different filenames conflict semantically or whether a NIF/texture is aesthetically preferable. MO2 priority expresses the user's choice.

## Selection and workflow

1. Select profile and review a checkbox tree of mods, separators, and nested TrueFolders. Include search, select all eligible, clear, and tri-state parent checkboxes. Selecting a parent includes descendants; individual children can be unticked. Sorting/search must not change membership or priority semantics.
2. Select `Remove overwritten assets`. Optionally select `Combine selected assets`, enter one new output mod name, and choose `Remove copied assets from source mods`. Keep these actions distinct in the preview: a copied winner and an overwritten loser have different reasons for removal.
3. Scan into an immutable operation plan. Display per-mod and total counts/bytes, selected winner/source paths, exclusions, metadata confidence, and available manual recovery leads. State that changes affect shared mod folders across all profiles; do not scan other profiles or use them to protect files. Provide per-file exclusions and export before applying.
4. Apply exactly that reviewed plan after revalidation and durable logging. Show progress and cancellation at safe boundaries. Produce a run report with operation history and manual recovery information. Do not retain removed asset bytes.

The initial UI creates one combined output for the selected set per run. Batch generation of one output per separator can be added later if wanted.

## Confirmed GUI requirements

Provide a compact, resizable tool window with an MO2-style mod tree as its main area. Preserve the selected profile's actual priority order and TrueFolder nesting; do not alphabetically regroup mods. Show priority, mod name, and profile-enabled status. Profile-enabled status is informational and distinct from the operation's selection checkbox; selecting an asset operation does not toggle mods in MO2.

Each mod and separator has an operation checkbox. A separator checkbox selects its full scope, including nested sub-separators; users can untick individual mods afterward. Parent checkboxes show checked, unchecked, or partially checked state. Highlight checked mods and selected separator scopes so the pending operation is visible even when keyboard/mouse focus is elsewhere. Distinguish focused rows from checked operation targets, and use checkboxes/text as well as color. Disabled mods remain visible with their status and are ineligible for destructive operations.

Support expand/collapse, search, select all eligible, clear selection, and a persistent count of selected mods/assets. Search filters visibility only: hidden checked rows stay selected and the UI makes that clear. Selecting a separator always targets its complete scope, not only search-visible children. Keep priority order fixed in the initial version; this window does not reorder the user's MO2 modlist.

Place operation controls alongside or below the tree: `Remove overwritten assets`, independent NIF/DDS filters, `Combine selected assets`, output mod name, and `Remove copied assets from source mods`. Enable the output name and copied-source removal controls only when combining is checked. Provide `Scan / Preview`, followed by an apply control enabled for a current reviewed plan, plus operation history/log access. Display selected profile and selected-only conflict scope, a brief shared-folder impact/log-only recovery note, and progress/cancel state. Final layout remains adjustable during UI review.

## Confirmed conflict and profile rules

Only conflicts between selected enabled mods authorize deletion. At each eligible relative path, keep the highest-priority selected enabled provider and remove lower-priority selected enabled loose copies. Read priority and enabled status exclusively from the selected MO2 profile. A file with only one selected enabled provider is retained, even if an unselected mod overrides it.

An unticked mod is neither a deletion target nor a reason to delete a selected asset. Disabled mods neither justify removal nor have files removed. Unselected providers may be shown separately to explain the effective current-profile winner, but do not expand the cleanup scope. Distinguish the selected-set winner from the effective profile winner in reports.

Do not consult other profiles to determine conflicts, enablement, priorities, or protection. Removals change the physical shared mod folders and therefore affect all profiles. Record the selected profile and its order/enablement snapshot for diagnosis; do not promise preservation of any other profile's result.

## Combining assets without changing the result

Proposed combining behavior, consistent with selected-only cleanup: copy unique selected assets and the highest-priority selected enabled copy of every conflicting path. Include the selected winner even when an unselected mod overrides it. This produces a merged selected group. This implication is proposed for confirmation; do not silently use a full-profile-winners-only filter.

With interleaved unselected mods there may be no single output priority preserving every original winner. Calculate a valid placement or report that separate outputs/remaining loose overrides are required. Never silently pick a priority that changes winners. Placement checks use the selected profile only and cannot authorize deletion of unselected files.

Create a new name only; reject existing mod names, invalid paths, separator-like names, or output/source overlap. Build in staging, verify each copied file's SHA-256, then publish through MO2's createMod API. Set activation/placement through supported MO2 APIs and record prior state. Do not automatically disable source mods: they can still contain plugins, scripts, configuration, and other assets.

If removal of copied source assets is requested, verify the published output bytes and commit each original-to-output mapping to the log before deleting the original. Do not retain separate backups. Do not block removal based on other profiles; record that the output is enabled/positioned only in the selected profile. Source mods remain enabled for their other content.

Validate winning content hashes for every affected path before and after output placement and removals, including paths provided by unselected mods. Equal bytes may move to a different provider; differing bytes indicate failure. Refresh MO2 and verify its effective view as well as the planned resolution. Reject stale plans when mods, priorities, enablement, profile state, or file contents change.

## Confirmed recovery policy: logs only, manual restoration

The user explicitly does not want removed files saved. Do not create a vault, backup mod, recycle-bin copy, or automatic undo system. Keep durable logs outside MO2's virtualized mods/Data tree. Record exact original paths, SHA-256 hashes, sizes, timestamps/attributes, mod metadata, download filenames/paths, Nexus identifiers and stable page links where known, and overriding selected providers. For copied winners also record their combined-output paths.

Before any source removal, commit the complete per-file provenance and deletion intent to a durable journal plus a self-contained recovery log. If logging fails, stop before further deletions. Record completion separately. Publish outputs only after verification; remove copied sources only after output verification. Flush journal writes and reconcile interrupted operations against observed file state. Multi-file work is not one atomic filesystem transaction: deleted losers cannot be rolled back automatically under this policy.

Preflight free space, writable destinations, path containment, case collisions, long paths, and reparse points. Reject junction/symlink traversal outside approved roots. Block concurrent operations and MO2 launches during mutation; detect already running tools as far as practical and fail closed when safe access cannot be established. Revalidate source identity immediately before removal. Treat disk-full, locked files, refresh failures, and cancellation as recorded partial states, never success.

History supports filtering/export by run, source mod, asset path, archive, Nexus mod/file ID, and action status. Provide manual steps to find a download, identify a candidate archive member, and copy it back to the original mod-relative destination. An optional hash check can confirm whether a recovered file matches the recorded original. Retain the selected profile snapshot for diagnosis; do not blindly replace a subsequently edited profile.

A combined output can be selected in a later operation. Preserve upstream per-file provenance and operation links so its original source remains traceable across repeated merges. Record source names/absolute and relative paths as they existed at the time, even if mods are later renamed or reinstalled.

## Manual recovery limits and space savings

- Logs are recovery instructions and evidence, not copies of the asset bytes. Exact restoration depends on still having or obtaining matching originals.
- FOMOD path changes, multiple installed archives, generated assets, and post-install modifications prevent assuming that a download contains the same path or bytes. Identify such uncertainty explicitly; do not claim a candidate download is verified provenance.
- Missing download/Nexus metadata must be shown in preview and the log. It does not force backups or forbid removal, but these assets have limited or unknown manual recovery leads.
- Optional archive-member discovery and hash matching can improve the log later. They are not required to authorize removal under the user's chosen policy, and must not create persistent extracted backups.

Show separately: removed source bytes, created output bytes, temporary peak storage, estimated reclaimable bytes, and measured allocated-space changes where available. Copying winners and deleting the originals mainly relocates bytes; removing losing duplicates supplies most savings. Hardlinks and filesystem compression can make logical byte totals differ from actual savings; avoid hardlinks for outputs in v1 because later edits could change shared content.

## Provenance and reports

Use a versioned SQLite journal/catalog as the local durable record and write self-contained JSON/JSONL recovery records before deletion, with CSV and a readable HTML or text summary. The self-contained log must contain enough metadata to guide manual recovery without the database or this plugin. Logs belong outside playable assets; put only an appropriate generated-mod identity/summary in MO2 metadata.

Record run ID, UTC time and local display time, tool/schema version, MO2 instance/game/selected profile, selection and folder ancestry, selected-only resolution policy, selected-profile snapshot/digest, and action states/errors.

For each file record: original mod internal/display name and path; relative Data path; size, timestamps/attributes and SHA-256; action/reason; selected providers and selected winner; effective profile winner separately when known; winner mod metadata; source mod metadata snapshot; repository/game/Nexus mod and installed file IDs and stable page links; mod version; original installation archive name; matched local download paths and sanitized sidecar fields; verified archive member/hash when known; destination/output path; manual recovery confidence; and action status/errors. Preserve upstream provenance if the source is a previous combined output.

Represent metadata confidence explicitly: known mod-level source, candidate download, verified exact archive member, generated/modified, or unknown. Multiple installedFiles IDs are a set of possible origins, not evidence tying each asset to one ID. A hash records the original bytes' identity but cannot recreate them. Logs must distinguish planned, completed, skipped, failed, and interrupted/uncertain actions; do not imply that an absent file alone proves this program completed its deletion.

## BSA handoff

V1 creates loose-file outputs suitable for a later CAO workflow; it does not pack BSAs. Keep logs outside packing inputs. Packing can change precedence: loose files beat archived files, so a previously losing loose asset outside the selection can become the winner after packing. A later archive-readiness report should identify these paths and require separate resolution; it must not delete unselected assets automatically.

Archive names, loading plugins, archive ordering/limits, and files required loose need separate validation. Extension alone does not establish that an asset is safe to pack. NIF/DDS-only consolidation may leave necessary PBR/configuration companions in original mods; keep those mods enabled and explain those dependencies in the report. Revalidate after packing or modifying meshes/textures; the loose-output verification does not certify a later BSA.

## Implementation sequence and acceptance gates

1. Build a disposable fixture tree in this project with nested separators, three overlapping mods, independent winners, outside providers, disabled/hidden assets, multiple profiles, and sample metadata. Add a thin MO2 capability probe in an isolated portable test instance. No deployment into BOSSE.
2. Implement the read-only scanner/planner and checkbox UI. Compare winner decisions against MO2 and folder membership against the supplied TrueFolder rules. Export a dry-run report. Any read-only BOSSE scan remains opt-in and produces reports only in this project.
3. Implement durable journal, self-contained recovery logs, and history before enabling cleanup. Test manual recovery from fixture downloads against original hashes. Test incomplete metadata, multiple candidate archives, logging failure, interrupted copy/removal/publication, insufficient space, locked files, stale plans, and path escape. Confirm no removed bytes are retained and completed/uncertain states are reported accurately.
4. Enable selected cleanup in fixtures. Confirm only selected enabled eligible physical files change; selected winners survive; effective winning bytes in the selected profile remain identical; unselected and disabled providers never justify deletion; other profiles do not influence decisions; audit reasons explain every removal and retention.
5. Enable combine, validate placement, then optional source removal. Test interleaved outside mods, output name collision, empty selections, repeated runs, combined-output inputs, and cancellation. Confirm copied winners are verified and logged before source deletion, and other profiles are not modified to activate the output.
6. Package a plugin zip with installation instructions and exact tested MO2/Python bridge versions. Test in an isolated MO2 instance using a small copied real-world sample only after synthetic gates pass. Explicitly review before any live BOSSE mutation.

## Open product decisions

Confirmed by the user: no saved asset backups, logs for manual recovery; remove conflicts only between selected mods; read load order and enabled status only from the selected profile, accepting shared-folder effects across profiles. Initial implementation uses the best selected enabled copy of every selected asset path, including paths overridden by outside mods, rejects a merge when no single safe priority exists, and includes only assets under meshes/textures. The user authorized implementation and a disposable local testbed; live BOSSE mutation remains outside this test build.
