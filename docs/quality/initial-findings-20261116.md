# Initial quality expansion findings

This is an audit, not a waiver or claim of repaired runtime state.

## Broad test discovery

The initial local831-case discovery found42failures and6skips.783cases passed.
Failure identities are listed below; full traces stay in local ignored reports.
Several assert historical placement/inventory/activation assumptions or require
additional tools/artifacts. No test expectation, production source or blanket
xfail was changed to hide these failures. Expanded CI must stay under review until
these are individually classified/repaired. Six skips are also not successful
runtime acceptance; Linux-specific tests must run in the actual Linux lane.

- `tests.test_pr_agent_chart.PrAgentChartTest::test_template_renders_webhook_and_local_model`
- `tests.test_inventory.InventoryStructureTests::test_main_inventory_contains_every_node_and_only_connection_settings`
- `tests.test_inventory.ResolvedInventoryTests::test_connection_overlays_still_override_main_inventory`
- `tests.test_inventory.ResolvedInventoryTests::test_default_and_explicit_main_inventory_include_all_nodes`
- `tests.test_official_mcp::test_all_49_applications_are_audited_with_reason`
- `tests.test_official_mcp::test_native_n8n_mcp_is_exact_service_owned_without_bypassing_ui`
- `tests.test_prometheus_component_ownership::test_offline_source_is_immutable_shared_code_not_shared_ownership`
- `tests.test_rustfs_unified_origin.UnifiedOrigin::test_routes_are_guarded_and_exactly_prioritized`
- `tests.test_public_dns_zone::test_rustfs_names_additive_without_changes_to_existing_records`
- `tests.test_wishlist_vm105.WishlistMove::test_production_has_one_writer_exact_image_and_fails_closed_on_empty_data`
- `tests.test_wiki_socrat0_placement.WikiSocrat0PlacementTest::test_rendered_deployment_has_one_writer_and_new_claim`
- `tests.test_wiki_socrat0_placement.WikiSocrat0PlacementTest::test_retained_volume_matches_values_and_existing_directory`
- `tests.test_syncthing_scheduling.SyncthingSchedulingTests::test_explicit_node_selector_remains_an_additional_constraint`
- `tests.test_syncthing_scheduling.SyncthingSchedulingTests::test_only_nodes_with_sidecar_configuration_are_eligible`
- `tests.test_syncthing_scheduling.SyncthingSchedulingTests::test_private_gui_rejects_empty_enrollment`
- `tests.test_syncthing_scheduling.SyncthingSchedulingTests::test_public_gui_does_not_require_private_node_configuration`
- `tests.test_spi_bundle.FullServiceBundleTests::test_queue_identity_is_not_replaced_or_exposed_to_web`
- `tests.test_spi_queue_oidc.NativeAPIResponseTests::test_production_native_activation_stays_disabled_until_release`
- `tests.test_grafana_alert_links.AlertLinksTest::test_native_escaping`
- `tests.test_grafana_alert_links.AlertLinksTest::test_native_live_fingerprint`
- `tests.test_otel_litellm_rollout.LiteLLMRolloutTests::test_apply_is_blocked_before_cluster_access_without_verified_reload`
- `tests.test_otel_migration.MigrationPreflightTests::test_backup_assertion_has_a_verified_receipt`
- `tests.test_otel_migration.MigrationPreflightTests::test_cluster_collectors_move_without_reducing_budgets`
- `tests.test_otel_migration.MigrationPreflightTests::test_contract_preserves_archive_and_tv_defaults`
- `tests.test_otel_migration.MigrationPreflightTests::test_default_policy_never_authorizes_cutover`
- `tests.test_otel_migration.MigrationPreflightTests::test_disk_peak_uses_stricter_reserve`
- `tests.test_otel_migration.MigrationPreflightTests::test_empty_and_old_inventory_fail`
- `tests.test_otel_migration.MigrationPreflightTests::test_evaluate_does_not_change_inputs`
- `tests.test_otel_migration.MigrationPreflightTests::test_integrity_gate_links_to_the_unrepaired_source_incident`
- `tests.test_otel_migration.MigrationPreflightTests::test_invalid_capacity_fails_closed`
- `tests.test_otel_migration.MigrationPreflightTests::test_known_memory_pressure_blocks_new_stack`
- `tests.test_otel_migration.MigrationPreflightTests::test_missing_node_and_unhealthy_target_fail`
- `tests.test_otel_migration.MigrationPreflightTests::test_negative_budget_is_rejected`
- `tests.test_otel_migration.MigrationPreflightTests::test_ready_with_verified_prerequisites_and_capacity`
- `tests.test_otel_migration.MigrationPreflightTests::test_relocated_collectors_still_require_memory_on_socrat_0`
- `tests.test_otel_migration.MigrationPreflightTests::test_source_corruption_cannot_be_hidden_by_old_roundtrip_success`
- `tests.test_otel_migration.MigrationPreflightTests::test_stale_future_and_hostname_mismatch_fail`
- `tests.test_otel_read_boundary_and_pki.ReadBoundaryTests::test_application_reader_has_no_ca_host_or_write_permissions`
- `tests.test_cats_image.CatsImageTest::test_default_image_is_immutable_and_cacheable`
- `tests.test_cats_image.CatsImageTest::test_empty_digest_preserves_explicit_tag_support`
- `tests.test_traffic_light_argo.TrafficLightArgoTest::test_rendered_apply_annotation_stays_below_kubernetes_limit`
- `tests.test_traffic_light_direct_ip.DirectIpTest::test_rendered_probe_and_existing_authenticated_pipeline`

## Static findings

- Initial owned Python audit:1907semantic findings before adding the new clean
  quality implementation. Includes pre-existing parse/undefined-name problems in
  `scripts/grafana-app-admission.py` / `scripts/identity-litellm-cleanup.py`.
  This inventory is not an assertion these tools are safe to run.
- Raw non-template YAML:187initial findings; shell:2initial findings.
- Action security: deliberate trusted compiler publisher trigger, exact context.
- Ansible safety scan: reproduced `_AnsibleTaggedList` AttributeError, not a pass.
  No Ansible workload was executed; syntax/static tooling does not authorize it.
- Secret scan:51reviewed non-secret contexts, stored separately with exact hashes
  and individual explanations; no live credential accepted as technical debt.
- Helm/schema/KubeLinter: initial per-resource lint/coverage/intent findings are
  retained in `quality/debt/charts-*.json`. Unknown CRD schemas are not “valid”.

Numbers above are dated first-pass evidence. Subsequent generated/new-source
checks can increase or resolve counts; reports, not this receipt, are current.
