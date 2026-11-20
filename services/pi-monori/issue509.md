## What was run

Same command as the Mutation testing job: `make BASE=origin/main MUTATION_JOBS=20 m-back-diff` on commit `1b2f682` (`drop-lockfiles`), base `origin/main` `e2738ad781dfdbe01da14499ed5c2103ea350c1f`. Cold `mutants/` directory, so the Makefile passed `--skip-new-survivors`. Frontend Stryker was not part of this run.

mutmut 3.8.1 mutated every changed Python file under `server/app`, `ci/lib`, `ci/quality_graph`, and `common` (61 files, including files whose only diff is the copyright header). That is 14620 mutants. Status codes in `*.py.meta` `exit_code_by_key`: killed `1` (9270), no coverage `33` (2953), survived `0` (2373), timeout `-24` (24).

`mutmut` process exit was 0. The diff gate exit was 0.

## What the CI gate actually scores

`ci/lib/mutation_diff_gate.py` scores only mutants whose function lines changed versus the merge base. Re-ran that gate on the finished `mutants/` tree against an empty baseline, with and without `--skip-new-survivors`:

| Metric | Value |
| --- | ---: |
| Status | PASS |
| Killed | 426 |
| Survived | 0 |
| No coverage | 0 |
| New survivors | 0 |
| Considered | 426 |
| Score | 100.00% |
| Threshold | 90% |

So this run does not fail PR #502. The 2373 survivors and 2953 no-coverage mutants sit in functions the diff gate ignores. They are still real gaps if the goal is that a mutation anywhere in those files is caught.

## How to reproduce

```bash
make BASE=origin/main m-back-diff
```

`MUTATION_JOBS` defaults to the machine CPU count. After the run, survivors are keys whose `exit_code_by_key` value is `0`, no coverage is `33`, timeouts are `-24`. To see only what CI enforces:

```bash
uv run --locked --group mutation python -m monori.ci.lib.mutation_diff_gate \
  --mutants mutants --baseline "$EMPTY_DIR" --base origin/main --threshold 90 --summary /tmp/mut-gate.md
```

## What to fix

Do not weaken the gate and do not mark these as equivalent without checking the mutant. For a survivor, a test ran and stayed green, so either the test does not observe the behavior or the mutant is equivalent and the code can be simplified. For no coverage, mutmut found no test that executes the function. For a timeout, the mutant likely removed a bound and a test hung; the test needs a deadline or the code needs a bound that tests can see fail.

Names use mutmut's spelling: `x_` prefix, and `ǁ` between class and method.

### Timeouts (24)

```
monori.ci.quality_graph.checks.hardcoded_colors.x__functional_matches__mutmut_33
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_access_denied__mutmut_10
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_access_denied__mutmut_14
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_access_denied__mutmut_16
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_access_denied__mutmut_2
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_access_denied__mutmut_5
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_drive_sso_step__mutmut_2
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_raise_if_access_denied__mutmut_1
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_submit_otp__mutmut_4
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁawait_worker__mutmut_3
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁawait_worker__mutmut_6
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁensure_logged_in__mutmut_1
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁis_logged_in__mutmut_1
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁis_logged_in__mutmut_2
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁis_logged_in__mutmut_3
monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁis_logged_in__mutmut_5
monori.server.app.routers.admin_sql.x_leading_keyword__mutmut_32
monori.server.app.routers.admin_sql.x_leading_keyword__mutmut_34
monori.server.app.routers.admin_sql.x_leading_keyword__mutmut_4
monori.server.app.transfer_match.x__transfer_candidates__mutmut_19
monori.server.app.transfer_match.x__transfer_candidates__mutmut_25
monori.server.app.workbook.parser.x__month_range__mutmut_3
monori.server.app.workbook.parser.x__month_range__mutmut_4
monori.server.app.workbook.parser.x__month_range__mutmut_8
```

### Survivors by area

| Mutants | Area |
| ---: | --- |
| 351 | monori.ci.quality_graph.checks.frontend_measurement |
| 344 | monori.server.app.workbook |
| 266 | monori.server.app.routers |
| 259 | monori.server.app.connectors |
| 169 | monori.ci.lib.coverage_diff |
| 145 | monori.ci.lib.mutation_gate |
| 130 | monori.ci.quality_graph.checks.bundle_measurement |
| 121 | monori.server.app.db_records |
| 94 | monori.ci.lib.mutation_diff_gate |
| 67 | monori.server.app.transfer_service |
| 55 | monori.ci.lib.flaky_tests |
| 50 | monori.ci.lib.annotations |
| 45 | monori.ci.lib.npm_audit_gate |
| 43 | monori.server.app.importer |
| 39 | monori.server.app.ingest |
| 30 | monori.server.app.deps |
| 29 | monori.ci.lib.time_bombs |
| 22 | monori.ci.lib.no_comments |
| 21 | monori.ci.quality_graph.checks.hardcoded_colors |
| 16 | monori.server.app.admin |
| 14 | monori.server.app.auth |
| 13 | monori.server.app.sync_runner |
| 10 | monori.server.app.transfer_match |
| 9 | monori.server.app.db |
| 6 | monori.ci.lib.triple_quotes |
| 5 | monori.server.app.crypto |
| 4 | monori.common.json_values decode_json |
| 4 | monori.server.app.emails |
| 3 | monori.common.json_values integer_value |
| 3 | monori.server.app.sync_service |
| 3 | monori.server.app.main |
| 2 | monori.common.json_values optional_string |
| 1 | monori.server.app.security |

275 functions, 2373 mutants. Count is the number of surviving mutants in that function.

```
145 monori.ci.lib.mutation_gate.x_main
74 monori.ci.quality_graph.checks.bundle_measurement.x_compare
64 monori.ci.lib.coverage_diff.x_main
48 monori.ci.quality_graph.checks.frontend_measurement.x_load_navigation
45 monori.ci.lib.npm_audit_gate.x_main
44 monori.ci.quality_graph.checks.frontend_measurement.x_load_lighthouse
42 monori.ci.quality_graph.checks.frontend_measurement.x_write_outputs
41 monori.ci.lib.coverage_diff.x_diff_stats
41 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁensure_logged_in
40 monori.ci.quality_graph.checks.bundle_measurement.x_main
40 monori.ci.quality_graph.checks.frontend_measurement.x_write_error
37 monori.ci.quality_graph.checks.frontend_measurement.x_parse_args
37 monori.server.app.db_records.xǁCategoryRecordǁfrom_row
37 monori.server.app.transfer_service.x_detect
35 monori.server.app.routers.accounts.x__update_account_fields
31 monori.ci.lib.annotations.xǁSourceAnnotationǁfrom_json
28 monori.ci.quality_graph.checks.frontend_measurement.x_compare_measurements
27 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_run
24 monori.ci.lib.coverage_diff.x_build_report
24 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁdownload_and_parse
24 monori.server.app.routers.connections.x__load
24 monori.server.app.workbook.parser.x__sheet_sections
21 monori.ci.lib.mutation_diff_gate.x_report_verdict
21 monori.server.app.workbook.apply.x__upsert_categories
20 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁprune_cache
19 monori.ci.lib.time_bombs.x_parse_added_lines
18 monori.server.app.connectors.tbank_playwright.x_statement_header
18 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁawait_worker
18 monori.server.app.deps.x_snapshot
18 monori.server.app.workbook.parser.x__add_transaction_categories
17 monori.server.app.routers.connections.x__load_user_rules
17 monori.server.app.workbook.parser.x__find_keyword_block
16 monori.ci.lib.flaky_tests.x_patch_for_base
16 monori.ci.lib.mutation_diff_gate.x_parse_changed_lines
16 monori.server.app.db_records.xǁAccountRecordǁfrom_row
16 monori.server.app.routers.accounts.x__ensure_account_name_available
16 monori.server.app.routers.connections.x__finish_account
15 monori.ci.quality_graph.checks.frontend_measurement.x_classify_relative
14 monori.ci.lib.annotations.xǁSourceAnnotationǁ__post_init__
14 monori.ci.quality_graph.checks.frontend_measurement.x_main
14 monori.server.app.ingest.x_load_rules
14 monori.server.app.routers.connections.x__route_rows
14 monori.server.app.transfer_service.x_candidates
14 monori.server.app.workbook.parser.x__category_col
13 monori.ci.lib.mutation_diff_gate.x_gate_python
13 monori.ci.lib.no_comments.x_main
13 monori.server.app.db_records.xǁTransactionRecordǁfrom_row
13 monori.server.app.importer.x_parse_statement
13 monori.server.app.ingest.x_historical_day_counts
13 monori.server.app.workbook.parser.x__parse_categories
12 monori.ci.lib.mutation_diff_gate.x_changed_lines
12 monori.ci.quality_graph.checks.frontend_measurement.x_config_parts
12 monori.server.app.admin.x_record_api_usage
12 monori.server.app.routers.admin_sql.x_leading_keyword
12 monori.server.app.workbook.apply.x__upsert_groups
12 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_is_archived_final_balance
11 monori.ci.lib.flaky_tests.x__append_playwright_suite
11 monori.ci.quality_graph.checks.frontend_measurement.x_classify_ttfb
11 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁshot
11 monori.server.app.routers.auth_router.x__valid_email
10 monori.ci.lib.coverage_diff.x_load_baseline
10 monori.ci.quality_graph.checks.hardcoded_colors.x_scan_file
10 monori.server.app.auth.x_current_user
10 monori.server.app.connectors.tbank_playwright.x_decode_statement
10 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁask_sms
10 monori.server.app.db_records.xǁConnectionRecordǁfrom_row
10 monori.server.app.importer.xǁImportRowǁto_api_dict
10 monori.server.app.transfer_service.x_rejections
10 monori.server.app.workbook.apply.x__import_transactions
10 monori.server.app.workbook.parser.x__add_transaction_category
10 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_append_available_warning
9 monori.ci.quality_graph.checks.frontend_measurement.x_classify
9 monori.ci.quality_graph.checks.frontend_measurement.x_sorted_regressions
9 monori.ci.quality_graph.checks.frontend_measurement.x_write_json
9 monori.server.app.connectors.tbank_playwright.x__load_sync_playwright
9 monori.server.app.routers.accounts.x__clean_tails
9 monori.server.app.routers.accounts.x__require_account
9 monori.server.app.routers.accounts.x__update_icon_image
9 monori.server.app.routers.connections.x__linked_accounts
9 monori.server.app.workbook.apply.x_budget_conflicts
9 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_apply_seam_seed
8 monori.ci.lib.flaky_tests.x_parse_pytest_collection
8 monori.ci.quality_graph.checks.bundle_measurement.x_snapshot
8 monori.ci.quality_graph.checks.bundle_measurement.x_tier
8 monori.ci.quality_graph.checks.frontend_measurement.x_band
8 monori.server.app.importer.xǁImportRowǁ__getitem__
8 monori.server.app.routers.accounts.x__update_account_tails
8 monori.server.app.sync_runner.xǁRemoteRunnerǁ__init__
8 monori.server.app.workbook.apply.x__category_index
8 monori.server.app.workbook.parser.x__add_stated_categories
8 monori.server.app.workbook.parser.x__parse_sheets
8 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_apply_opening
7 monori.ci.lib.time_bombs.x_main
7 monori.server.app.routers.auth_router.x_create_user
7 monori.server.app.routers.connections.x__creds
7 monori.server.app.workbook.parser.x__parse_keywords
6 monori.ci.lib.coverage_diff.x_write_report
6 monori.ci.lib.mutation_diff_gate.x_append_empty_summary
6 monori.ci.lib.mutation_diff_gate.x_collect_mutation_stats
6 monori.ci.lib.mutation_diff_gate.x_record_mutant
6 monori.ci.lib.no_comments.x_python_files
6 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_access_denied
6 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_submit_pin
6 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_type_pin
6 monori.server.app.db.x_connect
6 monori.server.app.db_records.x__row_value
6 monori.server.app.db_records.xǁUserRecordǁfrom_row
6 monori.server.app.ingest.x_commit_rows
6 monori.server.app.routers.accounts.x__owned_connection
6 monori.server.app.routers.connections.x__sync_accounts
6 monori.server.app.transfer_service.x_list_transfers
6 monori.server.app.workbook.parser.x__add_grid_categories
6 monori.server.app.workbook.parser.x__year_summaries
6 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_append_adjustment_warnings
6 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_append_opening_warning
6 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_desired_balance
5 monori.ci.lib.coverage_diff.x_failure_reasons
5 monori.ci.lib.coverage_diff.xǁCoverageReportǁ__post_init__
5 monori.ci.lib.flaky_tests.xǁCommandAttemptRunnerǁrun
5 monori.ci.quality_graph.checks.frontend_measurement.x_format_delta
5 monori.ci.quality_graph.checks.frontend_measurement.x_report_sections
5 monori.ci.quality_graph.checks.hardcoded_colors.x__named_color_is_literal
5 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁclick_export_format
5 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁis_logged_in
5 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁrestore_profile
5 monori.server.app.crypto.x__encryption_key
5 monori.server.app.db_records.xǁSplitRecordǁfrom_row
5 monori.server.app.routers.connections.x__fail
5 monori.server.app.transfer_match.x_day_number
5 monori.server.app.workbook.parser.x__amount
5 monori.server.app.workbook.parser.x__transaction_totals
5 monori.server.app.workbook.parser.x__tx_header_index
4 monori.ci.lib.coverage_diff.x_group_findings
4 monori.ci.lib.coverage_diff.x_render_summary
4 monori.ci.lib.flaky_tests.x_parse_vitest_collection
4 monori.ci.lib.mutation_diff_gate.x_changed_functions
4 monori.ci.lib.mutation_diff_gate.x_mutant_function
4 monori.ci.quality_graph.checks.frontend_measurement.x_report_table
4 monori.ci.quality_graph.checks.frontend_measurement.x_worst_tier
4 monori.common.json_values.x_decode_json
4 monori.server.app.admin.x_admin_user
4 monori.server.app.auth.x__user_from_row
4 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_drive_sso_step
4 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_enter_quick_code
4 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_save_debug
4 monori.server.app.connectors.tbank_playwright.xǁ_PageAdapterǁwait_for_load_state
4 monori.server.app.db_records.xǁBudgetRecordǁfrom_row
4 monori.server.app.db_records.xǁGoalGroupRecordǁfrom_row
4 monori.server.app.db_records.xǁGroupRecordǁfrom_row
4 monori.server.app.deps.x__snapshot_transactions
4 monori.server.app.emails.x_canonical_email
4 monori.server.app.importer.xǁImportRowǁto_sync_dict
4 monori.server.app.ingest.x_existing_hash_counts
4 monori.server.app.routers.accounts.x__update_account_connection
4 monori.server.app.routers.accounts.x__validate_icon_image
4 monori.server.app.routers.connections.x__now
4 monori.server.app.routers.connections.x__require_crypto
4 monori.server.app.transfer_match.x__transfer_buckets
4 monori.server.app.workbook.apply.x__drop_already_present
4 monori.server.app.workbook.parser.x__category_kinds
4 monori.server.app.workbook.parser.x__layout_label_column
4 monori.server.app.workbook.parser.xǁ_CategoryCatalogǁadd_category
4 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_reconcile_month
3 monori.ci.lib.coverage_diff.x_normalize_lcov
3 monori.ci.lib.flaky_tests.x__validate_selectors
3 monori.ci.lib.flaky_tests.x_added_test_lines
3 monori.ci.lib.mutation_diff_gate.xǁFunctionLocationsǁ_visit_function
3 monori.ci.lib.no_comments.x_violations
3 monori.ci.lib.triple_quotes.x_added_python_lines
3 monori.ci.quality_graph.checks.frontend_measurement.x_classify_band_crossing
3 monori.ci.quality_graph.checks.frontend_measurement.x_threshold
3 monori.ci.quality_graph.checks.hardcoded_colors.x__functional_matches
3 monori.ci.quality_graph.checks.hardcoded_colors.x__line_matches
3 monori.common.json_values.x_integer_value
3 monori.server.app.db_records.x_row_int
3 monori.server.app.db_records.x_row_optional_int
3 monori.server.app.db_records.x_row_optional_str
3 monori.server.app.db_records.x_row_str
3 monori.server.app.deps.x_serialize_category
3 monori.server.app.importer.x_parse_amount_kop
3 monori.server.app.importer.xǁCategoryRuleǁ__getitem__
3 monori.server.app.main.x__serve_spa
3 monori.server.app.routers.accounts.x__validate_account_patch
3 monori.server.app.routers.accounts.x__validate_color
3 monori.server.app.routers.admin_sql.x_cell
3 monori.server.app.routers.connections.x__account_since
3 monori.server.app.routers.connections.x__mark_connected
3 monori.server.app.routers.connections.x__mark_error
3 monori.server.app.routers.connections.x__optional_int
3 monori.server.app.sync_runner.xǁRemoteRunnerǁstart
3 monori.server.app.sync_service.x__error
3 monori.server.app.workbook.parser.x__add_year_sections
3 monori.server.app.workbook.parser.x__find_layout
3 monori.server.app.workbook.parser.x__label_col
3 monori.server.app.workbook.parser.x__layout_bases
3 monori.server.app.workbook.parser.x__transaction_amount
3 monori.server.app.workbook.parser.x__year_seeds
3 monori.server.app.workbook.parser.x_parse_workbook
3 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_range
3 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_reconcile_category
3 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_record_category_adjustment
2 monori.ci.lib.annotations.xǁSourceAnnotationǁto_json
2 monori.ci.lib.coverage_diff.x_typescript_function
2 monori.ci.lib.flaky_tests.x_repository_path
2 monori.ci.lib.flaky_tests.x_validated_base
2 monori.ci.lib.time_bombs.x_scan_patch
2 monori.ci.lib.triple_quotes.x__findings
2 monori.common.json_values.x_optional_string
2 monori.server.app.connectors.base.x_get_connector_class
2 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ__init__
2 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_drive_sso_login
2 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_fill_credential
2 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁform_title
2 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁheadless
2 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁoperations_url
2 monori.server.app.connectors.tbank_playwright.xǁ_PageAdapterǁgoto
2 monori.server.app.db.x__alembic_config
2 monori.server.app.db_records.x_row_bool
2 monori.server.app.db_records.x_row_enum
2 monori.server.app.deps.x_serialize_transactions
2 monori.server.app.deps.x_serialize_user
2 monori.server.app.routers.connections.x__match_tail
2 monori.server.app.routers.connections.x__require_account_refs
2 monori.server.app.routers.connections.x__serialize_connection
2 monori.server.app.sync_runner.xǁRemoteRunnerǁ_unpack
2 monori.server.app.workbook.apply.x__import_budgets
2 monori.server.app.workbook.apply.x_apply_workbook
2 monori.server.app.workbook.parser.x__layout_offsets
2 monori.server.app.workbook.parser.x__parse_year_sheets
2 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_budgeted_total
2 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_record_available_residual
2 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_seam_balance
2 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_year_sheet
2 monori.server.app.workbook.parser.xǁ_TransactionReaderǁcategory
1 monori.ci.lib.annotations.x_grouped_annotations
1 monori.ci.lib.annotations.x_publish_workflow_annotations
1 monori.ci.lib.annotations.x_workflow_annotation_command
1 monori.ci.lib.coverage_diff.x_function_name
1 monori.ci.lib.flaky_tests.x_parse_playwright_collection
1 monori.ci.lib.mutation_diff_gate.x_append_step_summary
1 monori.ci.lib.mutation_diff_gate.xǁChangedFunctionsǁ_visit_function
1 monori.ci.lib.mutation_diff_gate.xǁFunctionLocationsǁ__init__
1 monori.ci.lib.time_bombs.x_timestamp_unit
1 monori.ci.lib.triple_quotes.x_scan_source
1 monori.ci.quality_graph.checks.frontend_measurement.x_format_delta_cell
1 monori.server.app.connectors.base.x_register
1 monori.server.app.connectors.base.xǁConnectorInfoǁ__getattr__
1 monori.server.app.connectors.tbank_playwright.xǁ_DownloadExpectationAdapterǁ__init__
1 monori.server.app.connectors.tbank_playwright.xǁ_PageAdapterǁexpect_download
1 monori.server.app.connectors.tbank_playwright.xǁ_PageAdapterǁfill
1 monori.server.app.connectors.tbank_playwright.xǁ_PageAdapterǁwait_for_timeout
1 monori.server.app.db.x_begin_write
1 monori.server.app.deps.x_serialize_tx
1 monori.server.app.importer.x_categorize
1 monori.server.app.importer.xǁParseErrorǁ__getitem__
1 monori.server.app.ingest.x_dedup_text
1 monori.server.app.ingest.x_drop_already_present
1 monori.server.app.routers.connections.x__optional_blob
1 monori.server.app.routers.connections.x__optional_str
1 monori.server.app.routers.connections.x__validate_credentials
1 monori.server.app.security.x__load_or_create_secret
1 monori.server.app.transfer_match.x__transfer_candidate
1 monori.server.app.workbook.apply.x__norm
1 monori.server.app.workbook.parser.x__blank_transaction_row
1 monori.server.app.workbook.parser.x__budget_totals
1 monori.server.app.workbook.parser.x__collect_budgets
1 monori.server.app.workbook.parser.x__kop
1 monori.server.app.workbook.parser.x__parse_year_sheet
1 monori.server.app.workbook.parser.x__warn_unknown_section_rows
1 monori.server.app.workbook.parser.x_account_slot
1 monori.server.app.workbook.parser.xǁ_Reconciliationǁ__post_init__
1 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_adjust_income_targets
1 monori.server.app.workbook.parser.xǁ_Reconciliationǁ_income_synthetic
1 monori.server.app.workbook.parser.xǁ_TransactionReaderǁcell
1 monori.server.app.workbook.spec.x_kop_from_rub
```

### No coverage by area

| Mutants | Area |
| ---: | --- |
| 1053 | monori.server.app.routers |
| 1008 | monori.server.app.workbook |
| 197 | monori.server.app.transfer_service |
| 173 | monori.ci.lib.flaky_tests |
| 138 | monori.server.app.db_records |
| 81 | monori.ci.quality_graph.checks.hardcoded_colors |
| 72 | monori.ci.lib.mutation_diff_gate |
| 62 | monori.ci.lib.triple_quotes |
| 41 | monori.server.app.connectors |
| 38 | monori.ci.lib.coverage_diff |
| 35 | monori.server.app.importer |
| 24 | monori.ci.lib.time_bombs |
| 12 | monori.server.app.auth |
| 10 | monori.ci.quality_graph.checks.flaky_tests |
| 9 | monori.server.app.value_types |

106 functions, 2953 mutants.

```
192 monori.server.app.workbook.export.x__transactions_sheet
112 monori.server.app.workbook.export.x__write_year_summary
102 monori.server.app.workbook.export.x__write_year_category
91 monori.server.app.workbook.export.x__write_monthly_dashdata
90 monori.server.app.routers.categories.x__move_category
90 monori.server.app.routers.imports.x__commit_workbook
89 monori.server.app.transfer_service.x_link
81 monori.ci.quality_graph.checks.hardcoded_colors.x_main
72 monori.ci.lib.mutation_diff_gate.x_main
65 monori.server.app.workbook.export.x__year_headers
61 monori.server.app.workbook.export.x__write_category_year_totals
57 monori.server.app.routers.imports.x__validate_import_categories
55 monori.server.app.routers.imports.x__detect_row_accounts
55 monori.server.app.routers.imports.x__load_user_rules
52 monori.server.app.workbook.export.x_build_workbook
50 monori.server.app.workbook.export.x__style_year_sheet
50 monori.server.app.workbook.export.x__write_year_group
49 monori.ci.lib.flaky_tests.x_main
49 monori.server.app.routers.imports.x__remember_markers
49 monori.server.app.routers.transactions.x__validate_split_parts
48 monori.server.app.db_records.xǁTransferRecordǁfrom_row
46 monori.server.app.routers.categories.x__update_category_name
43 monori.server.app.routers.imports.x__workbook_preview_summary
42 monori.server.app.db_records.xǁCategoryOwnershipRecordǁfrom_row
42 monori.server.app.routers.budgets.x__set_cell
42 monori.server.app.routers.imports.x__mark_duplicates
40 monori.ci.lib.flaky_tests.x_collected_test_from_json
38 monori.ci.lib.coverage_diff.x_changed_paths
37 monori.server.app.routers.categories.x__update_goal_fields
37 monori.server.app.transfer_service.x_split
35 monori.ci.lib.flaky_tests.xǁSubprocessExecutorǁ_run
35 monori.server.app.workbook.export.x__categories_sheet
34 monori.server.app.routers.imports.x__reject_currency_mismatch
33 monori.server.app.routers.transactions.x__resolve_category
32 monori.server.app.db_records.xǁTransferSplitRecordǁfrom_row
31 monori.server.app.workbook.export.x__write_year_groups
29 monori.server.app.routers.transactions.x__split_parent
28 monori.server.app.workbook.export.x__year_sheet
27 monori.server.app.routers.transactions.x__serialized_splits
26 monori.server.app.routers.imports.x__account_slots
26 monori.server.app.transfer_service.x_reject
26 monori.server.app.workbook.export.x__effective_transactions
25 monori.server.app.routers.transactions.x__replace_split_rows
25 monori.server.app.routers.transactions.x__validate_category_type
21 monori.ci.lib.triple_quotes.x_main
21 monori.ci.lib.triple_quotes.x_patch_for_base
21 monori.server.app.routers.categories.x__owned_category
20 monori.server.app.routers.categories.x__merge_keywords
20 monori.server.app.routers.categories.x__update_category_fields
20 monori.server.app.routers.imports.x__serialize_import_row
20 monori.server.app.workbook.export.x__effective_transaction
19 monori.ci.lib.time_bombs.x__patch_for_base
19 monori.server.app.workbook.export.x__dashdata_sheet
18 monori.ci.lib.flaky_tests.x_write_manifest
18 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_dismiss_interstitials
18 monori.server.app.transfer_service.x_detach_leg
16 monori.ci.lib.triple_quotes.x_scan_repository
16 monori.server.app.db_records.xǁCategorySignRecordǁfrom_row
15 monori.server.app.routers.transactions.x__resolve_account
15 monori.server.app.transfer_service.x_owned_tx
14 monori.server.app.importer.x__attr_name
14 monori.server.app.routers.imports.x__preview_workbook
14 monori.server.app.workbook.export.x__fill_band
13 monori.ci.lib.flaky_tests.x_collected_test_json
13 monori.server.app.routers.admin.x__count_since
13 monori.server.app.routers.admin_sql.x__audit
12 monori.server.app.auth.xǁAuthenticatedUserǁto_api_dict
12 monori.server.app.importer.xǁImportRowǁto_ingest_dict
12 monori.server.app.transfer_service.x_serialize_transfer
11 monori.server.app.workbook.export.x__money_cell
10 monori.ci.lib.flaky_tests.x_read_manifest
10 monori.ci.quality_graph.checks.flaky_tests.x_execute_manifest
10 monori.server.app.routers.admin.x__count
10 monori.server.app.routers.imports.x__owned_account
9 monori.server.app.routers.imports.x__read_workbook_upload
9 monori.server.app.value_types.x_validate_transaction_date
9 monori.server.app.workbook.export.x__month_activity
8 monori.ci.lib.flaky_tests.xǁSubprocessExecutorǁrun
8 monori.server.app.routers.transfers.x_account_exists
7 monori.server.app.connectors.tbank_playwright.xǁTBankPlaywrightConnectorǁ_return_to_home
7 monori.server.app.importer.xǁImportRowǁ__setitem__
7 monori.server.app.routers.admin.x__cutoff
7 monori.server.app.routers.imports.x__parse_or_400
7 monori.server.app.workbook.spec.x_kop_to_rub
6 monori.server.app.routers.imports.x__serialize_parse_error
6 monori.server.app.workbook.export.x__text
6 monori.server.app.workbook.spec.x_group_display
5 monori.ci.lib.time_bombs.x_patch_for_base
5 monori.server.app.connectors.tbank_playwright.xǁ_PageAdapterǁget_by_text
5 monori.server.app.connectors.tbank_playwright.xǁ_PageAdapterǁscreenshot
5 monori.server.app.workbook.spec.x_amount_display
5 monori.server.app.workbook.spec.x_group_type
4 monori.ci.lib.triple_quotes.x_validated_base
4 monori.server.app.routers.imports.x__serialize_workbook_error
4 monori.server.app.workbook.export.x__balance_font
3 monori.server.app.workbook.export.x_workbook_bytes
2 monori.server.app.connectors.tbank_playwright.xǁ_RawPageǁwait_for_load_state
2 monori.server.app.routers.imports.x__card_digits
2 monori.server.app.workbook.export.x__budget_index
2 monori.server.app.workbook.export.x__style_header
1 monori.server.app.connectors.tbank_playwright.xǁ_Pageǁget_by_text
1 monori.server.app.connectors.tbank_playwright.xǁ_Pageǁscreenshot
1 monori.server.app.connectors.tbank_playwright.xǁ_RawPageǁget_by_text
1 monori.server.app.connectors.tbank_playwright.xǁ_RawPageǁscreenshot
1 monori.server.app.importer.xǁImportRowǁget
1 monori.server.app.importer.xǁParseErrorǁto_api_dict
```

