# API contract inventory (WP-2c)

Every HTTP endpoint that `web/client/` or `web/python_client/` calls, the Flask route that serves it, and whether a contract case covers it, followed by every Relay operation the client sends through `POST /api/graphql`. `tests/contract/test_catalogue.py` reads both tables: a row marked `recorded` must have at least one case (for Relay rows, a case that sends that operation's text), a `deferred:` row must have none and must say why, and every case must name a row here. A handful of rows have no client caller; their "Called by" says why the cases need them.

- Paths are templates. `<id>` is the Potion item id (an integer, or the item's key where noted).
- Server paths are relative to the repository root. `a/` is `web/server/api/`, `r/` is `web/server/routes/`, `q/` is `web/server/api/query/`.
- Client paths are relative to `web/client/`. `pc/` is `web/python_client/`.
- Pages (`/overview`, `/dashboard/<slug>` and so on) are navigations, not API calls. FE-9's legacy-URL table in `e2e/` (WP-2e) covers them.
- Every `APIService` GET also carries a stray `{}` in its query string (jQuery serialises the empty `data` argument). The server ignores it, and the recorder does not reproduce it.

## How to run

```bash
tests/contract/stack/stack.sh up      # builds the image, generates secrets, starts the stack
eval "$(tests/contract/stack/stack.sh env)"
uv run --no-project --with requests python -m tests.contract.record --dry-run   # no network
uv run --no-project --with requests python -m tests.contract.record             # re-record
uv run --no-project --with pytest --with hypothesis --with jsonschema --with requests \
  pytest tests/contract -q -m "not stack"   # offline checks only
uv run --no-project --with pytest --with hypothesis --with jsonschema --with requests \
  pytest tests/contract -q -m stack         # replay against CONTRACT_BASE_URL
tests/contract/stack/stack.sh down
```

- Record against a fresh stack (`down`, then `up`): some list endpoints return everything in the database, so leftovers from an earlier run change their shape. Replay is idempotent: every case cleans up what it creates (`95-cleanup.json` last).
- In CI, give each job its own `CONTRACT_PROJECT` (compose project) and `CONTRACT_WEB_PORT` (loopback port), for example `CONTRACT_PROJECT=contract-$CI_JOB_ID`.
- The stack has no route to the internet (`internal: true` network); only a small forwarder publishes `127.0.0.1:$CONTRACT_WEB_PORT`.
- The stack scripts run on Linux only: `stack.sh` uses GNU `stat -c`, bash 4 `mapfile`, `sha256sum` and `$XDG_RUNTIME_DIR`, and builds `linux/amd64` images. On macOS, run them in a Linux VM or a CI runner.

## Endpoints

| Method | Path | Server route | Called by | Coverage |
|---|---|---|---|---|
| POST | `/api2/authentication/login` | a/authentication_api_models.py:34 | services/AuthenticationService/index.js:24; runner login | recorded |
| POST | `/api2/authentication/register` | a/authentication_api_models.py:79 | services/AuthenticationService/index.js:43 | recorded |
| POST | `/api2/authentication/forgot_password` | a/authentication_api_models.py:124 | services/AuthenticationService/index.js:54 | recorded |
| POST | `/api2/authentication/reset_password` | a/authentication_api_models.py:141 | services/AuthenticationService/index.js:65 | recorded |
| GET | `/api2/authentication/registration_data` | a/authentication_api_models.py:185 | services/AuthenticationService/index.js:77 | recorded |
| GET | `/api2/authentication/user_manager_info` | a/authentication_api_models.py:209 | services/AuthenticationService/index.js:85 | recorded |
| POST | `/authentication/login` | none (405 from the static catch-all) | pc/core.py:32 `AuthenticatedSession`, which then falls back to `X-Username`/`X-Password` headers | recorded |
| POST | `/api/timeout` | r/api.py:389 (since WP-0c a timeout also clears the JWT and CSRF cookies) | util/timeoutSession.js:42 (ZenClient) | recorded |
| GET | `/user/sign-out` | r/views/flask_user_views.py:36 (Flask-User `user.logout`) | components/Navbar/MoreLinks.jsx:209 (`logoutUrl` from the server) | recorded |
| POST | `/api/authorization` | r/api.py:362 | services/AuthorizationService/index.js:64 | recorded |
| POST | `/api/authorization_multi` | r/api.py:368 | services/AuthorizationService/index.js:77 | recorded |
| GET | `/api/field/<field_ids>` | r/api.py:374 (since WP-0c unknown ids are 404 and more than 20 ids 400) | services/FieldInfoService.js:37 (ZenClient) | recorded |
| GET | `/api/field_names` | r/api.py:381 | components/common/SharingUtil/ShareQueryModal/index.jsx:334 (download) | recorded |
| POST | `/api/graphql` | r/api.py:397 (proxy to Hasura `/v1beta1/relay`) | util/graphql/environment.js:22 (Relay; per-operation coverage in the Relay table below) | recorded |
| POST | `/api/validate_self_serve_upload` | r/api.py:435 | services/AdminService.js:21 (multipart) | recorded |
| POST | `/api/import_self_serve` | r/api.py:429 | components/AdminApp/ConfigurationTab/SelfServeControlBlock/ImportSelfServeWrapper.jsx:144 (multipart) | recorded |
| GET | `/api/download_data_catalog_changes` | r/api.py:441 | ImportSelfServeWrapper.jsx:105 (download) | recorded |
| POST | `/api/import_data_catalog_fields_csv` | r/api.py:449 | components/AdminApp/ConfigurationTab/SelfServeControlBlock/ImportFieldsFromCSVWrapper.jsx:61 (multipart) | recorded |
| GET | `/api/export_self_serve` | r/api.py:413 | components/AdminApp/ConfigurationTab/SelfServeControlBlock/index.jsx:47 (download) | recorded |
| GET | `/api/export_data_catalog_metadata` | r/api.py:421 | components/AdminApp/ConfigurationTab/SelfServeControlBlock/index.jsx:54 (download) | recorded |
| GET | `/<map overlay geojson>` | static file named by `ui.MAP_GEOJSON_LOCATION` | components/visualizations/MapViz/QueryResultLayer/ShapeLayer/fetchGeoJsonTiles.js:27 | deferred: a deployment static asset, not an API |
| GET | `/api2/metadata/server_version` | a/metadata.py:26 | pc/core.py:161 | recorded |
| GET | `/api2/metadata/data_sources` | a/metadata.py:30 | services/ConfigurationService.js:104 | recorded |
| GET | `/api2/data_digest/tree` | a/metadata.py:44 | services/DataDigestService.js:205 | deferred: reads object storage, which the stack does not run (500 without it) |
| POST | `/api2/data_digest/object` | a/metadata.py:48 | services/DataDigestService.js:189 | deferred: reads object storage, which the stack does not run |
| GET | `/api2/configuration` | a/configuration_api_models.py:19 | no client (ConfigurationService.js:83 reads one key at a time); recorded because it lists every configuration key in one response | recorded |
| GET | `/api2/configuration/<key>` | a/configuration_api_models.py:19 | services/ConfigurationService.js:83 | recorded |
| POST | `/api2/configuration/<key>/set` | a/configuration_api_models.py:90 | services/ConfigurationService.js:125 | recorded |
| POST | `/api2/configuration/<key>/reset` | a/configuration_api_models.py:58 | services/ConfigurationService.js:139 | recorded |
| GET | `/api2/user` | a/user_api_models.py:80 | services/DirectoryService.js:256, :372; pc/directory_service/service.py:19, :24 | recorded |
| POST | `/api2/user` | a/user_api_models.py:80 (Potion create) | pc/directory_service/service.py:38 | recorded |
| GET | `/api2/user/<id>` | a/user_api_models.py:80 | services/DirectoryService.js:280; models/AlertsApp/AlertDefinition.js:100 | recorded |
| PATCH | `/api2/user/<id>` | a/user_api_models.py:131 | services/DirectoryService.js:437; pc/directory_service/service.py:55 | recorded |
| DELETE | `/api2/user/<id>` | a/user_api_models.py:80 | services/DirectoryService.js:400; pc/directory_service/service.py:76 | recorded |
| DELETE | `/api2/user/<id>/force` | a/user_api_models.py:221 | services/DirectoryService.js:422 | recorded |
| POST | `/api2/user/invite` | a/user_api_models.py:234 | services/DirectoryService.js:323; pc/directory_service/service.py:45 | recorded |
| GET | `/api2/user/<id>/ownership` | a/user_api_models.py:354 | services/DirectoryService.js:294 | recorded |
| GET | `/api2/user/<id>/is_user_in_group` | a/user_api_models.py:366 | services/DirectoryService.js:309; components/Navbar/util.jsx:130 | recorded |
| POST | `/api2/user/<id>/reset_password` | a/user_api_models.py:193 | services/DirectoryService.js:357; pc/directory_service/service.py:72 | recorded |
| POST | `/api2/user/<id>/password` | a/user_api_models.py:170 | pc/directory_service/service.py:68 | recorded |
| PATCH | `/api2/user/<id>/roles` | a/user_api_models.py:314 | services/DirectoryService.js:464; pc/directory_service/service.py:63 | recorded |
| GET | `/api2/user/<id>/can_export_data` | a/user_api_models.py:333 | services/DirectoryService.js:483 | recorded |
| POST | `/api2/user/<id>/generate_api_token` | a/user_api_models.py:152 | services/DirectoryService.js:502 | recorded |
| GET | `/api2/group` | a/group_api_models.py:62 | services/DirectoryService.js:58, :82; pc/directory_service/service.py:84, :90 | recorded |
| POST | `/api2/group` | a/group_api_models.py:96 | services/DirectoryService.js:184; pc/directory_service/service.py:102 | recorded |
| PATCH | `/api2/group/<id>` | a/group_api_models.py:120 | services/DirectoryService.js:116, :205; pc/directory_service/service.py:116 | recorded |
| DELETE | `/api2/group/<id>` | a/group_api_models.py:140 | services/DirectoryService.js:229; pc/directory_service/service.py:80 | recorded |
| PATCH | `/api2/group/<id>/roles` | a/group_api_models.py:172 | services/DirectoryService.js:139; pc/directory_service/service.py:124 | recorded |
| PATCH | `/api2/group/<id>/users` | a/group_api_models.py:216 | services/DirectoryService.js:160; pc/directory_service/service.py:131 | recorded |
| GET | `/api2/resource` | a/permission_api_models.py:104 | services/AuthorizationService/index.js:129, :187 | recorded |
| GET | `/api2/resource/<id>` | a/permission_api_models.py:104 | services/AuthorizationService/index.js:155 | recorded |
| GET | `/api2/resource/<id>/roles` | a/permission_api_models.py:241 | services/AuthorizationService/index.js:236, :271 | recorded |
| POST | `/api2/resource/<id>/roles` | a/permission_api_models.py:188 | services/AuthorizationService/index.js:97 | recorded |
| GET | `/api2/resource_role` | a/permission_api_models.py:291 | services/AuthorizationService/index.js:306 | recorded |
| GET | `/api2/resource-type` | a/permission_api_models.py:58 | services/AuthorizationService/index.js:357 | recorded |
| GET | `/api2/role` | a/permission_api_models.py:320 | services/AuthorizationService/index.js:336 | recorded |
| POST | `/api2/role` | a/permission_api_models.py:374 | services/AuthorizationService/index.js:424 | recorded |
| GET | `/api2/role/<id>` | a/permission_api_models.py:320 | services/AuthorizationService/index.js:400 | recorded |
| PATCH | `/api2/role/<id>` | a/permission_api_models.py:389 | services/AuthorizationService/index.js:466 | recorded |
| DELETE | `/api2/role/<id>` | a/permission_api_models.py:400 | services/AuthorizationService/index.js:507 | recorded |
| PATCH | `/api2/role/<id>/users` | a/permission_api_models.py:535 | services/AuthorizationService/index.js:483 | recorded |
| GET | `/api2/role/num_users` | a/permission_api_models.py:503 | services/AuthorizationService/index.js:529 | recorded |
| GET | `/api2/query_policy` | a/query_api_models.py:34 | services/AuthorizationService/index.js:378; pc/authorization_service/service.py:21 | recorded |
| POST | `/api2/query_policy` | a/query_api_models.py:34 (Potion create) | pc/authorization_service/service.py:38 | recorded |
| PATCH | `/api2/query_policy/<id>` | a/query_api_models.py:34 | pc/authorization_service/service.py:31 | recorded |
| DELETE | `/api2/query_policy/<id>` | a/query_api_models.py:34 | no client; the contract cases use it to clean up after `client.query_policy.create` | recorded |
| GET | `/api2/dashboard` | a/dashboard_api_models.py:376 | services/DashboardBuilderApp/DashboardService.js:63, :98, :375; pc/dashboard_service/service.py:21, :31 | recorded |
| POST | `/api2/dashboard` | a/dashboard_api_models.py:363 | services/DashboardBuilderApp/DashboardService.js:431; pc/dashboard_service/service.py:52 | recorded |
| GET | `/api2/dashboard/editable` | a/dashboard_api_models.py:502 | services/DashboardBuilderApp/DashboardService.js:110 | recorded |
| GET | `/api2/dashboard/viewable` | a/dashboard_api_models.py:400 | services/DashboardBuilderApp/DashboardService.js:171 | recorded |
| POST | `/api2/dashboard/upgrade_spec` | a/dashboard_api_models.py:549 | services/DashboardBuilderApp/DashboardService.js:367 | recorded |
| POST | `/api2/dashboard/transfer/username` | a/dashboard_api_models.py:624 | services/DashboardBuilderApp/DashboardService.js:558 | recorded |
| GET | `/api2/dashboard/<id>` | a/dashboard_api_models.py:714 | services/DashboardBuilderApp/DashboardService.js:133, :163; pc/dashboard_service/service.py:25 | recorded |
| PATCH | `/api2/dashboard/<id>` | a/dashboard_api_models.py:733 | services/DashboardBuilderApp/DashboardService.js:191; pc/dashboard_service/service.py:46 | recorded |
| DELETE | `/api2/dashboard/<id>` | a/dashboard_api_models.py:305 | services/DashboardBuilderApp/DashboardService.js:448 | recorded |
| POST | `/api2/dashboard/<id>/favorite` | a/dashboard_api_models.py:654 | services/DashboardBuilderApp/DashboardService.js:280 | recorded |
| POST | `/api2/dashboard/<id>/official` | a/dashboard_api_models.py:640 | services/DashboardBuilderApp/DashboardService.js:309 | recorded |
| POST | `/api2/dashboard/<id>/set_tile_data_permissions` | a/dashboard_api_models.py:673 | services/DashboardBuilderApp/DashboardService.js:339 | recorded |
| POST | `/api2/dashboard/<id>/add_item` | a/dashboard_api_models.py:563 | services/DashboardBuilderApp/DashboardService.js:523 | recorded |
| POST | `/api2/dashboard/<id>/transfer/username` | a/dashboard_api_models.py:593 | services/DashboardBuilderApp/DashboardService.js:601 | recorded |
| POST | `/api2/dashboard/<id>/share_via_email` | a/dashboard_api_models.py:744 | services/DashboardBuilderApp/DashboardService.js:652 | recorded |
| POST | `/api2/dashboard/<id>/cannot_view` | a/dashboard_api_models.py:440 | services/DashboardBuilderApp/DashboardService.js:683 | recorded |
| GET | `/api2/dashboard_session/<hash>` | a/dashboard_session_api_models.py:8 | services/DashboardBuilderApp/DashboardSessionService.js:28 | recorded |
| POST | `/api2/dashboard_session/generate_link` | a/dashboard_session_api_models.py:23 | services/DashboardBuilderApp/DashboardSessionService.js:52 | recorded |
| GET | `/api2/user_query_session/<hash>/by_query_uuid` | a/user_query_session_api_models.py:34 | services/QuerySessionService.js:30 | recorded |
| POST | `/api2/user_query_session/generate_link` | a/user_query_session_api_models.py:44 | services/QuerySessionService.js:69 | recorded |
| POST | `/api2/share/email` | a/share_analysis_api_models.py:25 | services/SendEmailService.js:63 | recorded |
| GET | `/api2/storage/retrieve` | a/thumbnail_storage_models.py:15 (Redis cache; Urlbox render on a miss) | services/ThumbnailStorageService.js:25 | recorded |
| GET | `/api2/alert_definitions` | a/alerts_api_models.py:107 | services/AlertsService.js:57; pc/alerts_service/service.py:22 | recorded |
| POST | `/api2/alert_definitions` | a/alerts_api_models.py:123 | services/AlertsService.js:78 | recorded |
| GET | `/api2/alert_definitions/<id>` | a/alerts_api_models.py:76 | services/AlertsService.js:36; pc/alerts_service/service.py:28 | recorded |
| PATCH | `/api2/alert_definitions/<id>` | a/alerts_api_models.py:76 | services/AlertsService.js:94 | recorded |
| DELETE | `/api2/alert_definitions/<id>` | a/alerts_api_models.py:76 | services/AlertsService.js:104 | recorded |
| GET | `/api2/alert_definitions/latest_notifications` | a/alerts_api_models.py:166 | services/AlertsService.js:114 | recorded |
| POST | `/api2/alert_definitions/transfer/username` | a/alerts_api_models.py:148 | services/AlertsService.js:217 | recorded |
| GET | `/api2/alert_notifications` | a/alerts_api_models.py:204 | services/AlertsService.js:191; pc/alerts_service/service.py:43 | recorded |
| GET | `/api2/alert_notifications/all_filtered` | none; falls through to `GET /api2/alert_notifications/<id>` | services/AlertsService.js:136 | recorded |
| GET | `/api2/alert_notifications/<id>` | a/alerts_api_models.py:204 | services/AlertsService.js:159 | recorded |
| PATCH | `/api2/alert_notifications/<id>` | a/alerts_api_models.py:204 | pc/alerts_service/service.py:66 | recorded |
| POST | `/api2/alert_notifications/bulk` | a/alerts_api_models.py:240 | pc/alerts_service/service.py:55 | recorded |
| PATCH | `/api2/alert_notifications/bulk` | a/alerts_api_models.py:254 | pc/alerts_service/service.py:73 | recorded |
| POST | `/api2/pipeline_run_metadata` | a/pipeline_runs_api_models.py:28 (Potion create) | no client; the pipeline writes these rows, and the cases seed two so digest and pipeline queries return items | recorded |
| DELETE | `/api2/pipeline_run_metadata/<id>` | a/pipeline_runs_api_models.py:28 | no client; the cases remove their seed rows | recorded |
| GET | `/api2/pipeline_run_metadata/digest_overview` | a/pipeline_runs_api_models.py:39 | services/DataDigestService.js:229 | recorded |
| POST | `/api2/data_upload_file_summary/update_csv_source` | a/data_upload_api_models.py:96 | services/DataUploadService.js:31 | deferred: needs a self-serve source and object storage |
| POST | `/api2/data_upload_file_summary/delete_source` | a/data_upload_api_models.py:106 | services/DataUploadService.js:43 | deferred: needs a self-serve source and object storage |
| POST | `/api2/data_upload_file_summary/upload_file/<source_id>` | a/data_upload_api_models.py:42 | services/DataUploadService.js:58 (multipart) | deferred: writes to object storage, which the stack does not run |
| POST | `/api2/data_upload_file_summary/validate_dataprep_input/<source_id>` | a/data_upload_api_models.py:52 | services/DataUploadService.js:74 (multipart) | deferred: needs a Dataprep flow and object storage |
| POST | `/api2/data_upload_file_summary/setup_new_dataprep` | a/data_upload_api_models.py:136 | services/DataUploadService.js:96 | deferred: calls the external Dataprep service |
| POST | `/api2/data_upload_file_summary/upload_and_start_dataprep_job` | a/data_upload_api_models.py:61 | services/DataUploadService.js:127 | deferred: calls the external Dataprep service |
| POST | `/api2/data_upload_file_summary/update_all_dataprep_jobs` | a/data_upload_api_models.py:87 | services/DataUploadService.js:147 | recorded |
| GET | `/api2/data_upload_file_summary/get_preview` | a/data_upload_api_models.py:116 | services/DataUploadService.js:172 | deferred: needs a self-serve source with uploaded files in object storage |
| GET | `/api2/data_upload_file_summary/get_sources_date_ranges` | a/data_upload_api_models.py:126 | services/DataUploadService.js:189 | recorded |
| POST | `/api2/data_upload_file_summary/clean_files` | a/data_upload_api_models.py:152 | services/DataUploadService.js:208 | deferred: deletes from object storage, which the stack does not run |
| GET | `/api2/data_upload_file_summary/download/<key>` | a/data_upload_api_models.py:169 | services/DataUploadService.js:246 (fetch, blob) | deferred: reads object storage, which the stack does not run |
| GET | `/api2/raw_pipeline_entity/search_metadata` | none (404) | services/EntityMatchingApp/EntityDimensionValueService.js:59 | recorded |
| GET | `/api2/query/granularities` | q/api_models.py:150 | services/wip/GranularityService.js:51 | recorded |
| GET | `/api2/query/dimension_values` | q/api_models.py:60 | services/wip/DimensionValueService.js:56 (`FullDimensionValueService`, unused) | recorded |
| GET | `/api2/query/dimension_values/frontend_cache` | q/api_models.py:81 | services/wip/DimensionValueService.js:61 | recorded |
| GET | `/api2/query/dimension_values/search/<dimension>` | q/api_models.py:118 | services/wip/DimensionValueSearchService.js:40 | recorded |
| GET | `/api2/query/fields` | none (404) | services/wip/FieldService.js:38 | recorded |
| GET | `/api2/query/categories` | none (404) | services/wip/CategoryService.js:96 | recorded |
| GET | `/api2/query/datasets` | none (404) | services/wip/DatasetService.js:31 | recorded |
| GET | `/api2/query/dimensions` | none (404) | services/wip/DimensionService.js:119 | recorded |
| GET | `/api2/query/dimensions/authorized` | none (404) | services/wip/DimensionService.js:114; components/AdvancedQueryApp/QueryFormPanel/QueryBuilder/FilterSelectionBlock/useFilterHierarchy.js:20 | recorded |
| GET | `/api2/query/field_metadata` | none (404) | services/wip/FieldMetadataService.js:46 | recorded |
| POST | `/api2/query/bar_graph` | q/query_models.py:97 | models/visualizations/BarGraph/BarGraphQueryEngine.js:18 (also box plot, histogram, bubble chart) | recorded |
| POST | `/api2/query/line_graph` | q/query_models.py:106 | models/visualizations/LineGraph/LineGraphQueryEngine.js:22 (also bump chart, heat tiles) | recorded |
| POST | `/api2/query/hierarchy` | q/query_models.py:115 | models/visualizations/ExpandoTree/ExpandoTreeQueryEngine.js:24 (also number trend, pie, sunburst) | deferred: the offline mock Druid client returns no TOTAL row, so shaping fails with 500; needs a Druid with harmony_demo data |
| POST | `/api2/query/map` | q/query_models.py:124 | models/visualizations/MapViz/MapQueryEngine.js:22 | recorded |
| GET | `/api2/query/table` | q/query_models.py:216 (`?h=<saved query hash>`) | components/AdvancedQueryApp/LiveResultsView/QueryResultActionButtons/ShareQueryModal/DownloadDataTab.jsx:51-60 (download link) | recorded |
| GET | `/api2/query/table/disaggregated` | q/query_models.py:220 (`?h=<saved query hash>`) | DownloadDataTab.jsx:51-60 (download link) | recorded |
| GET | `/dashboard/<name>/pdf` | r/page_renderer.py:85 | components/DashboardBuilderApp/DashboardHeader/DashboardControls/ShareDashboardModal/index.jsx:457 (download link) | deferred: renders through Urlbox, an external service the stack cannot reach; WP-1h replaces it with a self-hosted renderer |
| GET | `/dashboard/<name>/<session_hash>/pdf` | r/page_renderer.py:127 | ShareDashboardModal/index.jsx:457 (with shared settings) | deferred: renders through Urlbox (see above) |
| GET | `/dashboard/<name>/jpeg` | r/page_renderer.py:105 | ShareDashboardModal/index.jsx:479 (download link) | deferred: renders through Urlbox (see above) |
| GET | `/dashboard/<name>/<session_hash>/jpeg` | r/page_renderer.py:116 | ShareDashboardModal/index.jsx:479 (with shared settings) | deferred: renders through Urlbox (see above) |
| POST | `/api2/query/table` | q/query_models.py:193 | models/visualizations/Table/TableQueryEngine.js:19 | recorded |
| POST | `/api2/query/table/disaggregated` | q/query_models.py:203 | models/visualizations/Table/TableQueryEngine.js:29 | recorded |
| POST | `/api2/query/field_reporting_stats` | q/query_models.py:347 | components/common/QueryBuilder/CustomizableIndicatorTag/IndicatorCustomizationModule/IndicatorAboutPanel/useCalculationReportingStats.js:58 | recorded |
| POST | `/api2/query/data_quality` | q/query_models.py:254 | services/wip/DataQualityService.js:71 | recorded |
| POST | `/api2/query/data_quality_table` | q/query_models.py:281 | services/wip/DataQualityService.js:152 | recorded |
| POST | `/api2/query/reporting_completeness_line_graph` | q/query_models.py:292 | services/wip/DataQualityService.js:128 | recorded |
| POST | `/api2/query/outliers_box_plot` | q/query_models.py:305 | services/wip/DataQualityService.js:184 | recorded |
| POST | `/api2/query/outliers_line_graph` | q/query_models.py:319 | services/wip/DataQualityService.js:218 | recorded |
| POST | `/api2/query/outliers_table` | q/query_models.py:333 | services/wip/DataQualityService.js:254 | recorded |

## Relay operations

Sent as `{query, variables}` to `POST /api/graphql`. Cases load the text from the artifact (`relay:<path>`), so a changed query shows up as a changed request.

| Kind | Operation | Artifact | Coverage |
|---|---|---|---|
| mutation | BatchPublishModalMutation | `web/client/components/FieldSetupApp/FieldSetupPageHeaderActions/BatchPublishAction/__generated__/BatchPublishModalMutation.graphql.js` | recorded |
| mutation | CalculationInputMutation | `web/client/components/FieldSetupApp/UnpublishedFieldsTable/UnpublishedFieldTableRows/__generated__/CalculationInputMutation.graphql.js` | recorded |
| mutation | CalculationRowMutation | `web/client/components/DataCatalogApp/FieldDetailsPage/FieldDetailsSection/CalculationRow/__generated__/CalculationRowMutation.graphql.js` | recorded |
| mutation | CategoryGroupRowValueMutation | `web/client/components/DataCatalogApp/DirectoryPage/DirectoryTableContainer/DirectoryTable/DirectoryRow/__generated__/CategoryGroupRowValueMutation.graphql.js` | recorded |
| mutation | CategoryInputMutation | `web/client/components/FieldSetupApp/UnpublishedFieldsTable/UnpublishedFieldTableRows/__generated__/CategoryInputMutation.graphql.js` | recorded |
| mutation | CreateCalculationIndicatorViewMutation | `web/client/components/DataCatalogApp/common/CreateCalculationIndicatorView/__generated__/CreateCalculationIndicatorViewMutation.graphql.js` | recorded |
| mutation | CreateGroupModalMutation | `web/client/components/DataCatalogApp/common/GroupActionModals/__generated__/CreateGroupModalMutation.graphql.js` | recorded |
| mutation | DeleteCategoryModalMutation | `web/client/components/DataCatalogApp/common/GroupActionModals/__generated__/DeleteCategoryModalMutation.graphql.js` | recorded |
| mutation | DeleteFieldModalMutation | `web/client/components/DataCatalogApp/common/GroupActionModals/__generated__/DeleteFieldModalMutation.graphql.js` | recorded |
| mutation | DescriptionInputMutation | `web/client/components/FieldSetupApp/UnpublishedFieldsTable/UnpublishedFieldTableRows/__generated__/DescriptionInputMutation.graphql.js` | recorded |
| mutation | DescriptionRowMutation | `web/client/components/DataCatalogApp/FieldDetailsPage/FieldDetailsSection/__generated__/DescriptionRowMutation.graphql.js` | recorded |
| mutation | EditGroupModalMutation | `web/client/components/DataCatalogApp/common/GroupActionModals/__generated__/EditGroupModalMutation.graphql.js` | recorded |
| mutation | FieldCalculationSectionMutation | `web/client/components/DataCatalogApp/FieldDetailsPage/FieldCalculationSection/__generated__/FieldCalculationSectionMutation.graphql.js` | recorded |
| mutation | FieldRowValueMutation | `web/client/components/DataCatalogApp/DirectoryPage/DirectoryTableContainer/DirectoryTable/DirectoryRow/__generated__/FieldRowValueMutation.graphql.js` | recorded |
| mutation | NameInputMutation | `web/client/components/FieldSetupApp/UnpublishedFieldsTable/UnpublishedFieldTableRows/__generated__/NameInputMutation.graphql.js` | recorded |
| mutation | NameRowMutation | `web/client/components/DataCatalogApp/FieldDetailsPage/FieldDetailsSection/__generated__/NameRowMutation.graphql.js` | recorded |
| mutation | ShortNameInputMutation | `web/client/components/FieldSetupApp/UnpublishedFieldsTable/UnpublishedFieldTableRows/__generated__/ShortNameInputMutation.graphql.js` | recorded |
| mutation | ShortNameRowMutation | `web/client/components/DataCatalogApp/FieldDetailsPage/FieldDetailsSection/__generated__/ShortNameRowMutation.graphql.js` | recorded |
| mutation | UnpublishedFieldRowMutation | `web/client/components/FieldSetupApp/UnpublishedFieldsTable/UnpublishedFieldTableRows/__generated__/UnpublishedFieldRowMutation.graphql.js` | recorded |
| mutation | UpdateCalculationActionMutation | `web/client/components/FieldSetupApp/FieldSetupPageHeaderActions/__generated__/UpdateCalculationActionMutation.graphql.js` | recorded |
| mutation | UpdateCategoryActionMutation | `web/client/components/FieldSetupApp/FieldSetupPageHeaderActions/__generated__/UpdateCategoryActionMutation.graphql.js` | recorded |
| mutation | VisibilityRowMutation | `web/client/components/DataCatalogApp/FieldDetailsPage/FieldDetailsSection/__generated__/VisibilityRowMutation.graphql.js` | recorded |
| mutation | useBatchParentCategoryChangeMutation | `web/client/components/DataCatalogApp/DirectoryPage/hooks/ParentCategoryChange/__generated__/useBatchParentCategoryChangeMutation.graphql.js` | recorded |
| mutation | useDeleteSourceMutation | `web/client/components/DataUploadApp/SourceTable/__generated__/useDeleteSourceMutation.graphql.js` | recorded |
| mutation | useParentCategoryChangeForCategoryMutation | `web/client/components/DataCatalogApp/DirectoryPage/hooks/ParentCategoryChange/__generated__/useParentCategoryChangeForCategoryMutation.graphql.js` | recorded |
| mutation | useParentCategoryChangeForFieldMutation | `web/client/components/DataCatalogApp/DirectoryPage/hooks/ParentCategoryChange/__generated__/useParentCategoryChangeForFieldMutation.graphql.js` | recorded |
| mutation | useSelfServeMutation | `web/client/components/DataUploadApp/AddDataModal/__generated__/useSelfServeMutation.graphql.js` | recorded |
| query | BatchPublishModalContentsQuery | `web/client/components/FieldSetupApp/FieldSetupPageHeaderActions/BatchPublishAction/__generated__/BatchPublishModalContentsQuery.graphql.js` | recorded |
| query | BreadcrumbLeafItemQuery | `web/client/components/DataCatalogApp/DirectoryPage/BreadcrumbPath/__generated__/BreadcrumbLeafItemQuery.graphql.js` | recorded |
| query | BreadcrumbPathQuery | `web/client/components/DataCatalogApp/DirectoryPage/BreadcrumbPath/__generated__/BreadcrumbPathQuery.graphql.js` | recorded |
| query | CopyIndicatorViewWrapperQuery | `web/client/components/DataCatalogApp/common/CreateCalculationIndicatorView/__generated__/CopyIndicatorViewWrapperQuery.graphql.js` | recorded |
| query | CreateCalculationIndicatorViewQuery | `web/client/components/DataCatalogApp/common/CreateCalculationIndicatorView/__generated__/CreateCalculationIndicatorViewQuery.graphql.js` | recorded |
| query | DataStatusPageQuery | `web/client/components/DataUploadApp/__generated__/DataStatusPageQuery.graphql.js` | recorded |
| query | DataStatusPageSelfServeQuery | `web/client/components/DataUploadApp/__generated__/DataStatusPageSelfServeQuery.graphql.js` | recorded |
| query | DirectoryTableContainerQuery | `web/client/components/DataCatalogApp/DirectoryPage/DirectoryTableContainer/__generated__/DirectoryTableContainerQuery.graphql.js` | recorded |
| query | EditableCalculationQuery | `web/client/components/FieldSetupApp/UnpublishedFieldsTable/UnpublishedFieldTableRows/__generated__/EditableCalculationQuery.graphql.js` | recorded |
| query | FieldAboutPanelQuery | `web/client/components/AdvancedQueryApp/QueryFormPanel/QueryBuilder/FieldCustomizationModule/FieldAboutPanel/__generated__/FieldAboutPanelQuery.graphql.js` | recorded |
| query | FieldDetailsPageQuery | `web/client/components/DataCatalogApp/FieldDetailsPage/__generated__/FieldDetailsPageQuery.graphql.js` | recorded |
| query | QueryBuilderQuery | `web/client/components/AdvancedQueryApp/QueryFormPanel/QueryBuilder/__generated__/QueryBuilderQuery.graphql.js` | recorded |
| query | RecursiveCategoryBreadcrumbQuery | `web/client/components/DataCatalogApp/common/CategoryPath/__generated__/RecursiveCategoryBreadcrumbQuery.graphql.js` | recorded |
| query | UnpublishedFieldTableRowsPaginationQuery | `web/client/components/FieldSetupApp/UnpublishedFieldsTable/UnpublishedFieldTableRows/__generated__/UnpublishedFieldTableRowsPaginationQuery.graphql.js` | recorded |
| query | UnpublishedFieldTableRowsQuery | `web/client/components/FieldSetupApp/UnpublishedFieldsTable/UnpublishedFieldTableRows/__generated__/UnpublishedFieldTableRowsQuery.graphql.js` | recorded |
| query | UnpublishedFieldsTableContainerQuery | `web/client/components/FieldSetupApp/UnpublishedFieldsTableContainer/__generated__/UnpublishedFieldsTableContainerQuery.graphql.js` | recorded |
| query | patchDimensionServiceQuery | `web/client/components/DataCatalogApp/common/patchLegacyServices/__generated__/patchDimensionServiceQuery.graphql.js` | recorded |
| query | patchFieldMetadataServiceQuery | `web/client/components/DataCatalogApp/common/patchLegacyServices/__generated__/patchFieldMetadataServiceQuery.graphql.js` | recorded |
| query | patchFieldServiceQuery | `web/client/components/DataCatalogApp/common/patchLegacyServices/__generated__/patchFieldServiceQuery.graphql.js` | recorded |
| query | useDatasourceLookupQuery | `web/client/components/common/__generated__/useDatasourceLookupQuery.graphql.js` | recorded |
| query | useFieldHierarchyRootQuery | `web/client/components/common/QueryBuilder/FieldHierarchicalSelector/__generated__/useFieldHierarchyRootQuery.graphql.js` | recorded |
| query | usePipelineTimesHistoricalPipelinesQuery | `web/client/components/DataUploadApp/__generated__/usePipelineTimesHistoricalPipelinesQuery.graphql.js` | recorded |
| query | usePipelineTimesLastPipelineQuery | `web/client/components/DataUploadApp/__generated__/usePipelineTimesLastPipelineQuery.graphql.js` | recorded |
| query | usePipelineTimesLastSuccessfulPipelineQuery | `web/client/components/DataUploadApp/__generated__/usePipelineTimesLastSuccessfulPipelineQuery.graphql.js` | recorded |

## What phase 5 needs (QA-2)

Pointing `CONTRACT_BASE_URL` at FastAPI does not work as the suite stands. A phase-5 WP must supply:

- **Login.** `runner.Runner.session` logs `admin*` sessions in through `POST /api2/authentication/login?set_cookie=true` and sends `X-Username`/`X-Password` for `client*` sessions. WP-5d changes both (C-5) and adds CSRF on unsafe methods (SEC-5). Make login and CSRF a hook the runner calls, chosen per target.
- **A route map.** Cases name `/api` and `/api2` paths; new endpoints live under `/api/v3/` (BE-5). Either the strangler keeps the old paths (nginx or FastAPI aliases), or each case gains a mapping from its legacy route to the v3 route, and recordings whose shape deliberately changes (the C-10 error envelope, columnar `QueryResponse`) are re-recorded in that WP with the reason.
- **Query data.** Query cases run against Flask's `ZEN_OFFLINE` mock client, which invents rows; the Druid stub answers `[]` to `groupBy`. FastAPI has no such mock, so its query routes would return empty shapes and fail. Give the stub fixed rows for the recorded queries (or run a small Druid with `harmony_demo` data), and re-record queries once with Flask against that, so both stacks read the same rows.
- **Hasura.** The GraphQL cases go through Flask's proxy to Hasura; WP-5e retires both, so those recordings become the parity target for whatever replaces them.
- **Seeded catalogue rows.** `stack/seed_catalog.py` inserts the dimension, pipeline datasources, unpublished field, Dataprep flow and self-serve source that only the pipeline writes. A FastAPI stack needs the same rows (or the same script against its database) before replay.

## Server routes no client calls

These exist but neither client calls them, so they carry no contract case. Phase 5 still has to decide their fate: Potion's generic `GET /api2/<name>/schema` and `GET /api2/schema`; the default CRUD routes of `user_acl`, `group_acl`, `resource_role`, `api-token`, `source_config`, `pipeline_run_metadata` (except the create and delete the cases use to seed), `data_upload_file_summary`, `user_query_session` and `dashboard_session`; `GET /api/health` and `/api/hasura/health` (used by health checks);  the superuser-only dashboard maintenance routes (`/api2/dashboard/upgrade`, `/downgrade`, `/bulk_delete`, `/delete_all` and their `_all` and `raw_*` siblings); `/api2/query_policy/enabled_dimensions` and `/dimensions`; the thumbnail route `/dashboard/<name>/png/thumbnail`; and the Flask-User form routes (`POST /login`, `/user/change-password`, `/user/change-username`, `/user/profile`, `/user/reset-password/<token>`, `POST /zen/register`, `POST /user/forgot-password`).
