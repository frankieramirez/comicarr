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
| Bare-number filename, `auto` mode | `tests/unit/test_bare_numbers.py::test_auto_uses_volume_count_when_folder_matches_completed_set`, `tests/unit/test_bare_numbers.py::test_auto_treats_number_beyond_last_volume_as_chapter` | `tests/integration/test_acquisition_pipeline.py::test_manga_bare_number_auto_mode_reads_a_volume`, `tests/integration/test_acquisition_pipeline.py::test_manga_bare_number_auto_mode_reads_a_number_past_the_volumes_as_a_chapter` | covered |
| Bare-number filename, `volumes` mode | `tests/unit/test_bare_numbers.py::test_explicit_volumes_mode_reads_naruto_bare_number_as_volume` | `tests/integration/test_acquisition_pipeline.py::test_manga_bare_number_volumes_mode_reads_a_volume` | covered |
| Bare-number filename, `chapters` mode | `tests/unit/test_bare_numbers.py::test_explicit_chapters_mode_keeps_bare_number_as_chapter` | `tests/integration/test_acquisition_pipeline.py::test_manga_bare_number_chapters_mode_reads_a_chapter` | covered |
| `v`-prefixed volume | `tests/unit/test_bare_numbers.py::test_prefixed_volume_is_always_a_volume`, `tests/unit/test_manga_acquisition.py::test_volume_targets_search_v_prefix_not_chapter_tokens` | `tests/integration/test_acquisition_pipeline.py::test_manga_v_prefixed_volume_is_a_volume_in_any_mode`, `tests/integration/test_acquisition_pipeline.py::test_manga_volume_grab_is_recorded_as_snatched` | covered; recording the volume grab is an expected failure, #1279 |
| A volume covers its chapters without marking them Have | `tests/unit/test_manga_ledger.py::test_covered_fulfillment_is_not_have_and_is_not_searchable`, `tests/unit/test_manga_ledger.py::test_owning_a_volume_covers_only_mapped_chapters` | `tests/integration/test_acquisition_pipeline.py::test_manga_volume_covers_its_chapters_without_marking_them_have` | covered; expected failure until #1278 |
| Blended-frontier search terms | `tests/unit/test_manga_acquisition.py::test_blended_searches_missing_volumes_and_chapters_beyond`, `tests/unit/test_manga_ledger.py::test_blended_frontier_counts_volumes_then_chapters_beyond` | `tests/integration/test_acquisition_pipeline.py::test_manga_blended_frontier_searches_volumes_then_chapters_beyond`, `tests/integration/test_acquisition_pipeline.py::test_manga_downloaded_volume_leaves_the_blended_frontier` | covered; a downloaded volume leaving the frontier is an expected failure, #1278 |
| MangaDex ledger sync heals an empty ledger | `tests/unit/test_manga_sync.py::test_heal_empty_ledgers_reruns_add_for_md_and_mal`, `tests/unit/test_manga_recorded_responses.py::test_all_chapters_come_back_once_each_in_order` | `tests/integration/test_acquisition_pipeline.py::test_mangadex_ledger_sync_heals_an_empty_ledger` | covered |
| MAL-sourced series | `tests/unit/test_mal_prefix_drift.py::TestPostProcessingRoutesBothProviders::test_manga_ids_reach_the_manga_path`, `tests/unit/test_mal_prefix_drift.py::TestChapterPollCoversBothProviders::test_both_providers_are_polled_with_a_mangadex_id`, `tests/unit/test_manga_recorded_responses.py::test_mal_details_map_to_the_mangadex_shape`, `tests/unit/test_manga_recorded_responses.py::test_mal_id_resolves_to_the_mangadex_series_by_its_link` | `tests/integration/test_acquisition_pipeline.py::test_mal_sourced_series_reaches_the_library` | covered |
| Chapter placement in post-processing | `tests/unit/test_manga_postprocessor.py::TestProcessMangaChapterMatch::test_matches_chapter_and_updates_status`, `tests/unit/test_manga_postprocessor.py::TestProcessMangaFileMove::test_moves_files_to_series_folder` | `tests/integration/test_acquisition_pipeline.py::test_manga_chapter_is_placed_in_its_series_folder` | covered |
| Duplicate guard | `tests/unit/test_manga_duplicate_guard.py::test_adding_mal_id_is_refused_when_mangadex_row_has_that_mal_id`, `tests/unit/test_manga_postprocessor.py::TestProcessMangaExistingDestination::test_hardlink_rerun_is_idempotent` | `tests/integration/test_acquisition_pipeline.py::test_manga_duplicate_guard_refuses_the_same_work_from_mal`, `tests/integration/test_acquisition_pipeline.py::test_manga_second_release_of_an_owned_chapter_is_not_sent` | covered |
| Manga RSS | `tests/unit/test_manga_rss.py::TestMangaCheck::test_triggers_search_for_wanted_chapters` | `tests/integration/test_acquisition_pipeline.py::test_manga_rss_grabs_and_places_a_wanted_chapter` | covered |
| Add-manga failure narration | `tests/unit/test_add_manga_handoff.py::test_addvialist_narrates_add_failed_when_importer_raises`, `tests/unit/test_manga_recorded_responses.py::test_missing_mangadex_series_is_none_not_an_exception` | `tests/integration/test_acquisition_pipeline.py::test_manga_add_failure_is_narrated_in_activity` | covered |

## SABnzbd

| Scenario | Unit test | Pipeline test | Status |
|---|---|---|---|
| Handoff verified from SABnzbd's own response | `tests/unit/test_sab_recorded_responses.py::test_accepted_upload_returns_the_nzo_id_sab_assigned`, `tests/unit/test_sab_recorded_responses.py::test_rejected_upload_is_not_an_acceptance`, `tests/unit/test_sab_addfile_handoff.py::test_sender_rejects_an_acceptance_with_no_nzo_id` | `tests/integration/test_acquisition_pipeline.py::test_sab_handoff_is_verified_from_sabs_own_response`, `tests/integration/test_acquisition_pipeline.py::test_sab_rejected_upload_is_a_named_failure` | covered |
| Completed path with remote path mapping | `tests/unit/test_postprocess_input_resolution.py::test_sab_resolution_prefers_configured_job_directory` | `tests/integration/test_acquisition_pipeline.py::test_sab_completed_path_with_remote_path_mapping` | covered |
| Completed path without remote path mapping | `tests/unit/test_sab_recorded_responses.py::test_completed_history_slot_gives_the_download_folder`, `tests/unit/test_postprocess_input_resolution.py::test_sab_resolution_keeps_passed_folder_when_job_is_nested_there` | `tests/integration/test_acquisition_pipeline.py::test_sab_completed_path_without_remote_path_mapping` | covered |
| Missing completed path | `tests/unit/test_postprocess_input_resolution.py::test_missing_sab_paths_stop_before_processing`, `tests/unit/test_cdh_completed_path.py::test_cdh_monitor_owned_records_file_not_found_as_manual_review` | `tests/integration/test_acquisition_pipeline.py::test_sab_missing_completed_path_goes_to_manual_review` | covered |
| History entry removed before Comicarr reads it | `tests/unit/test_sab_recorded_responses.py::test_job_missing_from_history_is_reported_removed`, `tests/unit/test_sab_completed_reconcile.py::test_monitor_still_reviews_a_snatched_row_whose_job_vanished` | `tests/integration/test_acquisition_pipeline.py::test_sab_history_removed_before_comicarr_reads_it` | covered |
| Failed download leads to a retry | `tests/unit/test_sab_recorded_responses.py::test_failed_history_slot_is_a_failed_job_to_retry`, `tests/unit/test_cdh_completed_path.py::test_cdh_monitor_owned_failed_in_sab_retries_when_handling_on` | `tests/integration/test_acquisition_pipeline.py::test_sab_failed_download_leads_to_a_retry` | covered |
| Category routing | `tests/unit/test_sab_addfile_handoff.py::test_sender_posts_the_cached_nzb_as_content`, `tests/unit/test_sab_history_removal.py::test_historycheck_sends_configured_category_by_default` | `tests/integration/test_acquisition_pipeline.py::test_sab_category_routing` | covered |
| Restart mid-download | `tests/unit/test_sab_recorded_responses.py::test_queue_reports_a_downloading_job`, `tests/unit/test_recovery_replay.py::test_sab_queue_hit_reenqueues_nzb_monitor` | `tests/integration/test_acquisition_pipeline.py::test_sab_restart_mid_download_resumes_monitoring`, `tests/integration/test_acquisition_pipeline.py::test_sab_restart_with_a_current_comicvine_issue_id` | covered; the current-IssueID case is an expected failure, #1261 |
| Wrong API key is a connection failure | `tests/unit/test_sab_recorded_responses.py::test_wrong_api_key_is_reported_as_rejected`, `tests/unit/test_sab_recorded_responses.py::test_wrong_api_key_upload_is_not_an_acceptance` | `tests/integration/test_acquisition_pipeline.py::test_sab_wrong_api_key_is_a_connection_failure` | covered; expected failure until #1260 |
| Unreachable host is a connection failure | `tests/unit/test_sab_recorded_responses.py::test_unreachable_sab_raises_instead_of_reporting_the_job_gone`, `tests/unit/test_recovery_classify.py::test_sab_connection_error_during_historycheck_is_unreachable_not_gone` | `tests/integration/test_acquisition_pipeline.py::test_sab_unreachable_host_is_a_connection_failure` | covered |

## NZBGet

| Scenario | Unit test | Pipeline test | Status |
|---|---|---|---|
| Append handoff | `tests/unit/test_nzbget_recorded_responses.py::test_append_returns_the_nzbid_nzbget_assigned` | `tests/integration/test_acquisition_pipeline.py::test_nzbget_append_handoff_is_verified_from_nzbgets_own_response` | covered |
| History polling | `tests/unit/test_nzbget_recorded_responses.py::test_processor_polls_the_queue_until_the_job_reaches_history` | `tests/integration/test_acquisition_pipeline.py::test_nzbget_history_polling_follows_the_job_into_history` | covered |
| Destination directory mapping | `tests/unit/test_nzbget_recorded_responses.py::test_history_dest_dir_is_mapped_into_nzbget_directory`, `tests/unit/test_nzbget_recorded_responses.py::test_history_dest_dir_is_used_as_is_when_comicarr_can_see_it`, `tests/unit/test_postprocess_input_resolution.py::test_nzbget_resolution_preserves_existing_override_order`, `tests/unit/test_postprocess_input_resolution.py::test_nzbget_resolution_finds_download_under_category_subdirectory` | `tests/integration/test_acquisition_pipeline.py::test_nzbget_destination_directory_mapping` | covered |
| Par failure maps to a failure reason | `tests/unit/test_nzbget_recorded_responses.py::test_par_failure_is_a_failed_download` | `tests/integration/test_acquisition_pipeline.py::test_nzbget_par_failure_leads_to_a_retry`, `tests/integration/test_acquisition_pipeline.py::test_nzbget_failure_reason_names_what_failed[par]` | covered; the reason naming the cause is an expected failure, #1264 |
| Unpack failure maps to a failure reason | `tests/unit/test_nzbget_recorded_responses.py::test_unpack_failure_is_a_failed_download` | `tests/integration/test_acquisition_pipeline.py::test_nzbget_unpack_failure_leads_to_a_retry`, `tests/integration/test_acquisition_pipeline.py::test_nzbget_failure_reason_names_what_failed[unpack]` | covered; the reason naming the cause is an expected failure, #1264 |
| Health failure maps to a failure reason | `tests/unit/test_nzbget_recorded_responses.py::test_health_failure_is_a_failed_download` | `tests/integration/test_acquisition_pipeline.py::test_nzbget_health_failure_leads_to_a_retry`, `tests/integration/test_acquisition_pipeline.py::test_nzbget_failure_reason_names_what_failed[health]` | covered; the reason naming the cause is an expected failure, #1264 |
| Restart mid-download | `tests/unit/test_nzbget_recorded_responses.py::test_restart_probe_finds_a_finished_job_in_history`, `tests/unit/test_nzbget_recorded_responses.py::test_restart_probe_finds_the_job_from_the_saved_handoff` | `tests/integration/test_acquisition_pipeline.py::test_nzbget_restart_mid_download_resumes_monitoring`, `tests/integration/test_acquisition_pipeline.py::test_nzbget_restart_after_the_job_finished_resumes_handling` | covered; expected failure until #1263 |
| Authentication failure | `tests/unit/test_nzbget_recorded_responses.py::test_wrong_password_upload_is_not_an_acceptance`, `tests/unit/test_nzbget_recorded_responses.py::test_wrong_password_probe_is_reported_as_rejected`, `tests/unit/test_nzbget_recorded_responses.py::test_right_password_probe_reports_the_version` | `tests/integration/test_acquisition_pipeline.py::test_nzbget_wrong_password_is_an_authentication_failure` | covered |

## How the download-client tests run

Pipeline tests run Comicarr's real handoff, monitor, completed-download
handling and post-processing, and stop only at the download client. That
client is an in-process fake: `tests/fakes/sabnzbd.py` for SABnzbd and
`tests/fakes/nzbget.py` for NZBGet. Their responses are built from files
recorded from a real release in `tests/fixtures/sabnzbd/<version>/` and
`tests/fixtures/nzbget/<version>/`; each directory's README names the release
and how to record a fresh set. Manga scenarios that add their series through the real importer answer
from `tests/fakes/manga.py`, whose MangaDex and MyAnimeList responses were
recorded from the live APIs into `tests/fixtures/mangadex/` and
`tests/fixtures/myanimelist/` (see `tests/fixtures/mangadex/README.md`). The
manga RSS scenario downloads its NZB from `tests/fakes/newznab.py`. The
fakes refuse any request to a host
they do not serve, so no test reaches the network. Shared pipeline steps live
in `tests/fakes/pipeline.py`.

Manga pipeline tests start from the series' blended-frontier search plan and
its search terms, hand the release to the SABnzbd fake, and run the manga
branch of post-processing against chapter rows laid out as the MangaDex import
writes them (`tests/fakes/pipeline.py`).

A scenario that exposes a bug keeps its test, marked as an expected failure
that links the bug. The Status column names it.

## Checking the recordings against the real clients

A recording drifts when a client release changes its responses, and the fakes
would keep replaying the old shape. The nightly `Download client contracts`
workflow (`.github/workflows/client-contracts.yml`) starts the pinned images,
replays the same exchanges as the recorders, and compares each live response
with its recording by shape: keys, value types and status codes, never values.
A key the client stopped sending, a new key, or a changed type fails the run
and names the recording and field. It never gates a pull request; run it by
hand from the Actions tab with *Run workflow*. Locally, `pytest tests/contract`
skips unless `SAB_CONTRACT_URL` and `SAB_CONTRACT_APIKEY`, or
`NZBGET_CONTRACT_URL`, `NZBGET_CONTRACT_USERNAME` and
`NZBGET_CONTRACT_PASSWORD`, point at disposable instances.

| Client | Pinned image | Recordings |
|---|---|---|
| SABnzbd | `linuxserver/sabnzbd:5.1.3-ls281` | `tests/fixtures/sabnzbd/5.1.3/` |
| NZBGet | `linuxserver/nzbget:v26.3-ls271` | `tests/fixtures/nzbget/26.3/` |

To move to a new client release:

1. Run the recorder against the new image, as that fixture directory's
   README describes. It writes a new `<version>/` directory.
2. Point `VERSION` in `tests/fakes/sabnzbd.py` or `tests/fakes/nzbget.py` at it.
3. Change the image in the workflow's `env` block and in the table above.
4. Run `pytest tests/unit tests/integration/test_acquisition_pipeline.py`, then
   dispatch the workflow on the branch before merging.

When the nightly run fails on an unchanged pin, the image tag was rebuilt or
the comparison found a field that depends on the job; read the reported field
before re-recording.

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
| SABnzbd | `comicarr/sabnzbd.py` | 82.3% of 395 lines (78.0% before #1219) | 82.3% | met |
| NZBGet | `comicarr/nzbget.py` | 56.4% of 220 lines (6.4% before #1220) | 56.4% | 23.6 |
| Manga | `comicarr/app/manga/` | 91.3% of 526 lines (91.1% before #1221) | 91.3% | met |
| Downloads | `comicarr/app/downloads/handoff.py`, `completed_path.py`, `sab_reconcile.py` | 84.3% of 350 lines | 84.3% | met |
