# First-class test targets

Manga, SABnzbd and NZBGet are first-class test targets
([Foundations plan, section 5](../architecture/foundations-plan.md#5-first-class-test-targets)).
A target is first-class when every scenario below has a unit test and at least
one test in `tests/integration/test_acquisition_pipeline.py` that runs from a
search result to the final library state.

Each row names the tests that prove it. A cell that says `pending` is a known
gap, owned by the build ticket in the Status column.
`scripts/check_first_class_targets.py` (under `npm run lint:guards`) fails when a
row names a test that does not exist, when a `pending` cell is not on the
script's `PENDING` list, and when a `PENDING` entry no longer matches a cell.
The list only shrinks: filling a cell means deleting its entry in the same
change.

## Manga

| Scenario | Unit test | Pipeline test | Status |
|---|---|---|---|
| Bare-number filename, `auto` mode | `tests/unit/test_bare_numbers.py::test_auto_uses_volume_count_when_folder_matches_completed_set`, `tests/unit/test_bare_numbers.py::test_auto_treats_number_beyond_last_volume_as_chapter` | pending | pending #1221 |
| Bare-number filename, `volumes` mode | `tests/unit/test_bare_numbers.py::test_explicit_volumes_mode_reads_naruto_bare_number_as_volume` | pending | pending #1221 |
| Bare-number filename, `chapters` mode | `tests/unit/test_bare_numbers.py::test_explicit_chapters_mode_keeps_bare_number_as_chapter` | pending | pending #1221 |
| `v`-prefixed volume | `tests/unit/test_bare_numbers.py::test_prefixed_volume_is_always_a_volume`, `tests/unit/test_manga_acquisition.py::test_volume_targets_search_v_prefix_not_chapter_tokens` | pending | pending #1221 |
| A volume covers its chapters without marking them Have | `tests/unit/test_manga_ledger.py::test_covered_fulfillment_is_not_have_and_is_not_searchable`, `tests/unit/test_manga_ledger.py::test_owning_a_volume_covers_only_mapped_chapters` | pending | pending #1221 |
| Blended-frontier search terms | `tests/unit/test_manga_acquisition.py::test_blended_searches_missing_volumes_and_chapters_beyond`, `tests/unit/test_manga_ledger.py::test_blended_frontier_counts_volumes_then_chapters_beyond` | pending | pending #1221 |
| MangaDex ledger sync heals an empty ledger | `tests/unit/test_manga_sync.py::test_heal_empty_ledgers_reruns_add_for_md_and_mal` | pending | pending #1222 |
| MAL-sourced series | `tests/unit/test_mal_prefix_drift.py::TestPostProcessingRoutesBothProviders::test_manga_ids_reach_the_manga_path`, `tests/unit/test_mal_prefix_drift.py::TestChapterPollCoversBothProviders::test_both_providers_are_polled_with_a_mangadex_id` | pending | pending #1222 |
| Chapter placement in post-processing | `tests/unit/test_manga_postprocessor.py::TestProcessMangaChapterMatch::test_matches_chapter_and_updates_status`, `tests/unit/test_manga_postprocessor.py::TestProcessMangaFileMove::test_moves_files_to_series_folder` | pending | pending #1222 |
| Duplicate guard | `tests/unit/test_manga_duplicate_guard.py::test_adding_mal_id_is_refused_when_mangadex_row_has_that_mal_id`, `tests/unit/test_manga_postprocessor.py::TestProcessMangaExistingDestination::test_hardlink_rerun_is_idempotent` | pending | pending #1222 |
| Manga RSS | `tests/unit/test_manga_rss.py::TestMangaCheck::test_triggers_search_for_wanted_chapters` | pending | pending #1222 |
| Add-manga failure narration | `tests/unit/test_add_manga_handoff.py::test_addvialist_narrates_add_failed_when_importer_raises` | pending | pending #1222 |

## SABnzbd

| Scenario | Unit test | Pipeline test | Status |
|---|---|---|---|
| Handoff verified from SABnzbd's own response | `tests/unit/test_sab_addfile_handoff.py::test_sender_uses_the_first_nzo_id_when_sab_returns_several`, `tests/unit/test_sab_addfile_handoff.py::test_sender_rejects_an_acceptance_with_no_nzo_id` | pending | pending #1219 |
| Completed path with remote path mapping | `tests/unit/test_postprocess_input_resolution.py::test_sab_resolution_prefers_configured_job_directory` | pending | pending #1219 |
| Completed path without remote path mapping | `tests/unit/test_postprocess_input_resolution.py::test_sab_resolution_keeps_passed_folder_when_job_is_nested_there` | pending | pending #1219 |
| Missing completed path | `tests/unit/test_postprocess_input_resolution.py::test_missing_sab_paths_stop_before_processing`, `tests/unit/test_cdh_completed_path.py::test_cdh_monitor_owned_records_file_not_found_as_manual_review` | pending | pending #1219 |
| History entry removed before Comicarr reads it | `tests/unit/test_sab_completed_reconcile.py::test_monitor_still_reviews_a_snatched_row_whose_job_vanished`, `tests/unit/test_recovery_classify.py::test_sab_absent_no_done_signal_reachable_is_gone` | pending | pending #1219 |
| Failed download leads to a retry | `tests/unit/test_cdh_completed_path.py::test_cdh_monitor_owned_failed_in_sab_retries_when_handling_on` | pending | pending #1219 |
| Category routing | `tests/unit/test_sab_addfile_handoff.py::test_sender_posts_the_cached_nzb_as_content`, `tests/unit/test_sab_history_removal.py::test_historycheck_sends_configured_category_by_default` | pending | pending #1219 |
| Restart mid-download | `tests/unit/test_recovery_replay.py::test_sab_queue_hit_reenqueues_nzb_monitor` | pending | pending #1219 |
| Wrong API key is a connection failure | `tests/unit/test_health_results_and_connections.py::test_sabnzbd_rejected_key_is_a_failure` | pending | pending #1219 |
| Unreachable host is a connection failure | `tests/unit/test_recovery_classify.py::test_sab_connection_error_during_historycheck_is_unreachable_not_gone` | pending | pending #1219 |

## NZBGet

| Scenario | Unit test | Pipeline test | Status |
|---|---|---|---|
| Append handoff | pending | pending | pending #1220 |
| History polling | pending | pending | pending #1220 |
| Destination directory mapping | `tests/unit/test_postprocess_input_resolution.py::test_nzbget_resolution_preserves_existing_override_order`, `tests/unit/test_postprocess_input_resolution.py::test_nzbget_resolution_finds_download_under_category_subdirectory` | pending | pending #1220 |
| Par failure maps to a failure reason | pending | pending | pending #1220 |
| Unpack failure maps to a failure reason | pending | pending | pending #1220 |
| Health failure maps to a failure reason | pending | pending | pending #1220 |
| Restart mid-download | pending | pending | pending #1220 |
| Authentication failure | pending | pending | pending #1220 |

## Coverage baseline

Line coverage from the backend test workflow's run: the unit suite, then the
integration suite appended (`-m "not slow"`), measured on 2026-11-13. The target
is 80% of lines. The floors live in `COVERAGE_FLOORS` in
`scripts/check_first_class_targets.py`, and the workflow fails when a group
falls below its floor (`python3 scripts/check_first_class_targets.py --coverage coverage.xml`).
Floors only rise: when a change raises a figure, record the new one in both
places.

| Group | Modules | Lines covered | Floor | Points to 80% |
|---|---|---|---|---|
| SABnzbd | `comicarr/sabnzbd.py` | 78.0% of 395 lines | 78.0% | 2.0 |
| NZBGet | `comicarr/nzbget.py` | 6.4% of 220 lines | 6.4% | 73.6 |
| Manga | `comicarr/app/manga/` | 91.1% of 528 lines | 91.1% | met |
| Downloads | `comicarr/app/downloads/handoff.py`, `completed_path.py`, `sab_reconcile.py` | 84.3% of 350 lines | 84.3% | met |
