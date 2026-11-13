BEGIN TRANSACTION;
CREATE TABLE acquisition_canary_permits (
	permit_id VARCHAR(64) NOT NULL, 
	repair_run_id VARCHAR(64) NOT NULL, 
	release_key VARCHAR(512) NOT NULL, 
	route VARCHAR(32) NOT NULL, 
	actor_id VARCHAR(255) NOT NULL, 
	session_digest VARCHAR(64) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	expires_at VARCHAR(40) NOT NULL, 
	lease_id VARCHAR(64), 
	claimed_at VARCHAR(40), 
	completed_at VARCHAR(40), 
	outcome VARCHAR(64), 
	PRIMARY KEY (permit_id), 
	CONSTRAINT uq_acq_canary_repair_release UNIQUE (repair_run_id, release_key)
);
CREATE TABLE acquisition_maintenance (
	control_id VARCHAR(64) NOT NULL, 
	epoch INTEGER DEFAULT '0' NOT NULL, 
	active INTEGER DEFAULT '0' NOT NULL, 
	owner VARCHAR(255), 
	run_id VARCHAR(64), 
	reason TEXT, 
	acquired_at VARCHAR(40), 
	heartbeat_at VARCHAR(40), 
	released_at VARCHAR(40), 
	PRIMARY KEY (control_id)
);
INSERT INTO "acquisition_maintenance" VALUES('acquisition',0,0,NULL,NULL,NULL,NULL,NULL,NULL);
CREATE TABLE acquisition_maintenance_events (
	event_id INTEGER NOT NULL, 
	epoch INTEGER NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	actor VARCHAR(255) NOT NULL, 
	run_id VARCHAR(64), 
	reason TEXT NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (event_id)
);
CREATE TABLE acquisition_maintenance_leases (
	lease_id VARCHAR(64) NOT NULL, 
	epoch INTEGER NOT NULL, 
	owner VARCHAR(255) NOT NULL, 
	work_kind VARCHAR(64) NOT NULL, 
	entity_type VARCHAR(32), 
	entity_id VARCHAR(255), 
	acquired_at VARCHAR(40) NOT NULL, 
	heartbeat_at VARCHAR(40) NOT NULL, 
	released_at VARCHAR(40), 
	PRIMARY KEY (lease_id)
);
CREATE TABLE acquisition_reconciliation (
	control_id VARCHAR(64) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	reason VARCHAR(255), 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (control_id)
);
INSERT INTO "acquisition_reconciliation" VALUES('migration-reconciliation','ready',NULL,'2026-01-01T00:00:00+00:00');
CREATE TABLE acquisition_repair_canaries (
	canary_id VARCHAR(64) NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	entity_type VARCHAR(32) NOT NULL, 
	entity_id VARCHAR(255) NOT NULL, 
	owner_id VARCHAR(255) NOT NULL, 
	session_digest VARCHAR(64) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	confirmed_at VARCHAR(40) NOT NULL, 
	consumed_at VARCHAR(40), 
	PRIMARY KEY (canary_id), 
	CONSTRAINT uq_acq_repair_canary_run UNIQUE (run_id)
);
CREATE TABLE acquisition_repair_events (
	event_id INTEGER NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	sequence INTEGER, 
	action VARCHAR(32) NOT NULL, 
	actor_id VARCHAR(255) NOT NULL, 
	entity_type VARCHAR(32), 
	entity_id VARCHAR(255), 
	reason VARCHAR(255) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (event_id)
);
CREATE TABLE acquisition_repair_items (
	item_id INTEGER NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	sequence INTEGER NOT NULL, 
	entity_type VARCHAR(32) NOT NULL, 
	entity_id VARCHAR(255) NOT NULL, 
	series_id VARCHAR(255) NOT NULL, 
	intent VARCHAR(16) NOT NULL, 
	fulfillment VARCHAR(32) NOT NULL, 
	reason VARCHAR(64) NOT NULL, 
	date_source VARCHAR(32), 
	selected_date VARCHAR(10), 
	evidence_json TEXT NOT NULL, 
	before_json TEXT NOT NULL, 
	proposed_json TEXT NOT NULL, 
	optional INTEGER DEFAULT '0' NOT NULL, 
	selected INTEGER DEFAULT '0' NOT NULL, 
	apply_state VARCHAR(32) NOT NULL, 
	apply_reason VARCHAR(255), 
	applied_json TEXT, 
	rollback_state VARCHAR(32) NOT NULL, 
	rollback_reason VARCHAR(255), 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	applied_at VARCHAR(40), 
	rolled_back_at VARCHAR(40), 
	PRIMARY KEY (item_id), 
	CONSTRAINT uq_acq_repair_item_sequence UNIQUE (run_id, sequence), 
	CONSTRAINT uq_acq_repair_item_entity UNIQUE (run_id, entity_type, entity_id)
);
CREATE TABLE acquisition_repair_manifests (
	manifest_id VARCHAR(64) NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	preview_fingerprint VARCHAR(64) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	item_count INTEGER NOT NULL, 
	selected_count INTEGER NOT NULL, 
	frozen_by VARCHAR(255) NOT NULL, 
	frozen_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (manifest_id), 
	CONSTRAINT uq_acq_repair_manifest_run UNIQUE (run_id)
);
CREATE TABLE acquisition_repair_runs (
	run_id VARCHAR(64) NOT NULL, 
	scope_type VARCHAR(32) NOT NULL, 
	scope_id VARCHAR(255) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	actor_id VARCHAR(255) NOT NULL, 
	session_digest VARCHAR(64) NOT NULL, 
	preview_token_digest VARCHAR(64) NOT NULL, 
	token_expires_at VARCHAR(40) NOT NULL, 
	token_consumed_at VARCHAR(40), 
	preview_fingerprint VARCHAR(64) NOT NULL, 
	manifest_id VARCHAR(64), 
	maintenance_epoch INTEGER, 
	item_count INTEGER DEFAULT '0' NOT NULL, 
	selected_count INTEGER DEFAULT '0' NOT NULL, 
	applied_count INTEGER DEFAULT '0' NOT NULL, 
	conflict_count INTEGER DEFAULT '0' NOT NULL, 
	rollback_count INTEGER DEFAULT '0' NOT NULL, 
	rollback_conflict_count INTEGER DEFAULT '0' NOT NULL, 
	last_sequence INTEGER DEFAULT '0' NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	confirmed_at VARCHAR(40), 
	started_at VARCHAR(40), 
	updated_at VARCHAR(40) NOT NULL, 
	completed_at VARCHAR(40), 
	PRIMARY KEY (run_id)
);
CREATE TABLE acquisition_repair_series (
	series_item_id INTEGER NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	series_id VARCHAR(255) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	dirty INTEGER DEFAULT '0' NOT NULL, 
	aggregate_selected INTEGER DEFAULT '0' NOT NULL, 
	before_have INTEGER, 
	before_total INTEGER, 
	final_have INTEGER, 
	final_total INTEGER, 
	conflict_reason VARCHAR(255), 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (series_item_id), 
	CONSTRAINT uq_acq_repair_series_run UNIQUE (run_id, series_id)
);
CREATE TABLE acquisition_run_items (
	item_id INTEGER NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	command_kind VARCHAR(32) NOT NULL, 
	entity_type VARCHAR(32) NOT NULL, 
	entity_id VARCHAR(255) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	dispatch_state VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	queue_priority VARCHAR(16) DEFAULT 'routine' NOT NULL, 
	payload_json TEXT, 
	attempt_count INTEGER DEFAULT '0' NOT NULL, 
	next_attempt_at VARCHAR(40), 
	reason TEXT, 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	completed_at VARCHAR(40), 
	PRIMARY KEY (item_id), 
	CONSTRAINT uq_acquisition_run_item_identity UNIQUE (run_id, command_kind, entity_type, entity_id)
);
CREATE TABLE acquisition_runs (
	run_id VARCHAR(64) NOT NULL, 
	command_kind VARCHAR(32) NOT NULL, 
	"trigger" VARCHAR(64) NOT NULL, 
	scope_type VARCHAR(32), 
	scope_id VARCHAR(255), 
	dispatch_state VARCHAR(32) NOT NULL, 
	completion_state VARCHAR(32) NOT NULL, 
	accepted_count INTEGER DEFAULT '0' NOT NULL, 
	terminal_count INTEGER DEFAULT '0' NOT NULL, 
	succeeded_count INTEGER DEFAULT '0' NOT NULL, 
	no_match_count INTEGER DEFAULT '0' NOT NULL, 
	blocked_count INTEGER DEFAULT '0' NOT NULL, 
	failed_count INTEGER DEFAULT '0' NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	completed_at VARCHAR(40), 
	PRIMARY KEY (run_id)
);
CREATE TABLE acquisition_schema_versions (
	component VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	applied_at VARCHAR(40) NOT NULL, 
	CONSTRAINT uq_acquisition_schema_component_version UNIQUE (component, version)
);
INSERT INTO "acquisition_schema_versions" VALUES('acquisition',1,'2026-01-01T00:00:00+00:00');
INSERT INTO "acquisition_schema_versions" VALUES('acquisition',2,'2026-01-01T00:00:00+00:00');
INSERT INTO "acquisition_schema_versions" VALUES('acquisition',3,'2026-01-01T00:00:00+00:00');
INSERT INTO "acquisition_schema_versions" VALUES('acquisition',4,'2026-01-01T00:00:00+00:00');
INSERT INTO "acquisition_schema_versions" VALUES('acquisition',5,'2026-01-01T00:00:00+00:00');
INSERT INTO "acquisition_schema_versions" VALUES('acquisition',6,'2026-01-01T00:00:00+00:00');
CREATE TABLE acquisition_search_previews (
	preview_id VARCHAR(64) NOT NULL, 
	series_id VARCHAR(255) NOT NULL, 
	actor_id VARCHAR(255) NOT NULL, 
	session_digest VARCHAR(64) NOT NULL, 
	token_digest VARCHAR(64) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	eligible_json TEXT NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	run_id VARCHAR(64), 
	created_at VARCHAR(40) NOT NULL, 
	expires_at VARCHAR(40) NOT NULL, 
	confirmed_at VARCHAR(40), 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (preview_id), 
	CONSTRAINT uq_acquisition_search_preview_token UNIQUE (token_digest)
);
CREATE TABLE ai_activity_log (
	id INTEGER NOT NULL, 
	timestamp TEXT, 
	feature_type TEXT, 
	action_description TEXT, 
	model TEXT, 
	prompt_tokens INTEGER, 
	completion_tokens INTEGER, 
	latency_ms INTEGER, 
	success TEXT, 
	error_message TEXT, 
	entity_type TEXT, 
	entity_id TEXT, 
	PRIMARY KEY (id)
);
CREATE TABLE ai_cache (
	cache_key TEXT, 
	cache_type TEXT, 
	data TEXT, 
	created_at TEXT, 
	expires_at TEXT, 
	UNIQUE (cache_key)
);
CREATE TABLE ai_metadata_history (
	id INTEGER NOT NULL, 
	entity_type TEXT, 
	entity_id TEXT, 
	field_name TEXT, 
	original_value TEXT, 
	ai_value TEXT, 
	source TEXT, 
	provider TEXT, 
	created_at TEXT, 
	PRIMARY KEY (id)
);
CREATE TABLE annuals (
	"IssueID" TEXT, 
	"Issue_Number" TEXT, 
	"IssueName" TEXT, 
	"IssueDate" TEXT, 
	"Status" TEXT, 
	"AcquisitionIntent" VARCHAR(16), 
	"ComicID" TEXT, 
	"GCDComicID" TEXT, 
	"Location" TEXT, 
	"ComicSize" TEXT, 
	"Int_IssueNumber" INTEGER, 
	"ComicName" TEXT, 
	"ReleaseDate" TEXT, 
	"DigitalDate" TEXT, 
	"ReleaseComicID" TEXT, 
	"ReleaseComicName" TEXT, 
	"IssueDate_Edit" TEXT, 
	"DateAdded" TEXT, 
	"Deleted" INTEGER DEFAULT '0', 
	CONSTRAINT uq_annuals_issueid UNIQUE ("IssueID")
);
INSERT INTO "annuals" VALUES('920001','1',NULL,'2026-06-01','Downloaded','policy','900001',NULL,'Starfall Rangers Annual 001.cbz',NULL,1000,'Starfall Rangers Annual','2026-06-01',NULL,'900091','Starfall Rangers Annual',NULL,NULL,0);
CREATE TABLE comics (
	"ComicID" TEXT, 
	"ComicName" TEXT, 
	"ComicSortName" TEXT, 
	"ComicYear" TEXT, 
	"DateAdded" TEXT, 
	"Status" TEXT, 
	"IncludeExtras" INTEGER, 
	"Have" INTEGER, 
	"Total" INTEGER, 
	"ComicImage" TEXT, 
	"FirstImageSize" INTEGER, 
	"ComicPublisher" TEXT, 
	"PublisherImprint" TEXT, 
	"ComicLocation" TEXT, 
	"ComicPublished" TEXT, 
	"NewPublish" TEXT, 
	"LatestIssue" TEXT, 
	"intLatestIssue" INTEGER, 
	"LatestDate" TEXT, 
	"Description" TEXT, 
	"DescriptionEdit" TEXT, 
	"QUALalt_vers" TEXT, 
	"QUALtype" TEXT, 
	"QUALscanner" TEXT, 
	"QUALquality" TEXT, 
	"LastUpdated" TEXT, 
	"AlternateSearch" TEXT, 
	"UseFuzzy" TEXT, 
	"ComicVersion" TEXT, 
	"SortOrder" INTEGER, 
	"DetailURL" TEXT, 
	"ForceContinuing" INTEGER, 
	"ComicName_Filesafe" TEXT, 
	"AlternateFileName" TEXT, 
	"ComicImageURL" TEXT, 
	"ComicImageALTURL" TEXT, 
	"DynamicComicName" TEXT, 
	"AllowPacks" TEXT, 
	"Type" TEXT, 
	"Corrected_SeriesYear" TEXT, 
	"Corrected_Type" TEXT, 
	"TorrentID_32P" TEXT, 
	"LatestIssueID" TEXT, 
	"Collects" TEXT, 
	"IgnoreType" INTEGER, 
	"AgeRating" TEXT, 
	"FilesUpdated" TEXT, 
	"seriesjsonPresent" INTEGER, 
	dirlocked INTEGER, 
	cv_removed INTEGER, 
	not_updated_db TEXT, 
	"ContentType" TEXT DEFAULT 'comic', 
	"ReadingDirection" TEXT DEFAULT 'ltr', 
	"MetadataSource" TEXT, 
	"ExternalID" TEXT, 
	"MangaDexID" TEXT, 
	"MalID" TEXT, 
	UNIQUE ("ComicID")
);
INSERT INTO "comics" VALUES('900001','Starfall Rangers','Starfall Rangers','2019','2026-01-01','Active',NULL,0,0,NULL,NULL,'Matrix Press',NULL,'/library/comics/Starfall Rangers (2019)',NULL,NULL,'1',NULL,'2026-01-01',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'Print',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'comic','ltr',NULL,NULL,NULL,NULL);
INSERT INTO "comics" VALUES('900002','Harbor Lights','Harbor Lights','2021','2026-01-01','Paused',NULL,0,0,NULL,NULL,'Matrix Press',NULL,'/library/comics/Harbor Lights (2021)',NULL,NULL,'1',NULL,'2026-01-01',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'Print',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'comic','ltr',NULL,NULL,NULL,NULL);
INSERT INTO "comics" VALUES('900003','The Quiet Engine','The Quiet Engine','2015','2026-01-01','Active',NULL,0,0,NULL,NULL,'Matrix Press',NULL,'/library/comics/The Quiet Engine (2015)',NULL,NULL,'1',NULL,'2026-01-01',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'Print',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'comic','ltr',NULL,NULL,NULL,NULL);
INSERT INTO "comics" VALUES('md-0f5e1c2a-matrix','Lantern Garden','Lantern Garden','2020','2026-01-01','Active',NULL,0,0,NULL,NULL,'Matrix Press',NULL,'/library/manga/Lantern Garden (2020)',NULL,NULL,'1',NULL,'2026-01-01',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'Manga',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'manga','ltr',NULL,NULL,NULL,NULL);
CREATE TABLE ddl_info (
	"ID" TEXT, 
	series TEXT, 
	year TEXT, 
	filename TEXT, 
	size TEXT, 
	issueid TEXT, 
	comicid TEXT, 
	link TEXT, 
	status TEXT, 
	remote_filesize TEXT, 
	updated_date TEXT, 
	mainlink TEXT, 
	issues TEXT, 
	site TEXT, 
	submit_date TEXT, 
	pack INTEGER, 
	link_type TEXT, 
	tmp_filename TEXT, 
	oneoff INTEGER, 
	resume INTEGER, 
	comicinfo TEXT, 
	packinfo TEXT, 
	UNIQUE ("ID")
);
CREATE TABLE exceptions_log (
	date TEXT, 
	comicname TEXT, 
	issuenumber TEXT, 
	seriesyear TEXT, 
	issueid TEXT, 
	comicid TEXT, 
	booktype TEXT, 
	searchmode TEXT, 
	error TEXT, 
	error_text TEXT, 
	filename TEXT, 
	line_num TEXT, 
	func_name TEXT, 
	traceback TEXT, 
	UNIQUE (date)
);
CREATE TABLE failed (
	"ID" TEXT, 
	"Status" TEXT, 
	"ComicID" TEXT, 
	"IssueID" TEXT, 
	"Provider" TEXT, 
	"ComicName" TEXT, 
	"Issue_Number" TEXT, 
	"NZBName" TEXT, 
	"DateFailed" TEXT, 
	CONSTRAINT uq_failed_id_provider_nzbname UNIQUE ("ID", "Provider", "NZBName")
);
INSERT INTO "failed" VALUES('matrix-failed-1','Failed','900001','910004','MatrixNZB','Starfall Rangers','4','Starfall.Rangers.004.2019','2026-01-03 10:00:00');
CREATE TABLE futureupcoming (
	"ComicName" TEXT, 
	"IssueNumber" TEXT, 
	"ComicID" TEXT, 
	"IssueID" TEXT, 
	"IssueDate" TEXT, 
	"Publisher" TEXT, 
	"Status" TEXT, 
	"DisplayComicName" TEXT, 
	weeknumber TEXT, 
	year TEXT
);
CREATE TABLE importresults (
	"impID" TEXT, 
	"ComicName" TEXT, 
	"ComicYear" TEXT, 
	"Status" TEXT, 
	"ImportDate" TEXT, 
	"ComicFilename" TEXT, 
	"ComicLocation" TEXT, 
	"WatchMatch" TEXT, 
	"DisplayName" TEXT, 
	"SRID" TEXT, 
	"ComicID" TEXT, 
	"IssueID" TEXT, 
	"Volume" TEXT, 
	"IssueNumber" TEXT, 
	"DynamicName" TEXT, 
	"IssueCount" TEXT, 
	implog TEXT, 
	"MatchConfidence" INTEGER, 
	"SuggestedComicID" TEXT, 
	"SuggestedComicName" TEXT, 
	"SuggestedIssueID" TEXT, 
	"IgnoreFile" INTEGER DEFAULT '0', 
	"MatchSource" TEXT, 
	CONSTRAINT uq_importresults_impid UNIQUE ("impID")
);
CREATE TABLE issues (
	"IssueID" TEXT, 
	"ComicName" TEXT, 
	"IssueName" TEXT, 
	"Issue_Number" TEXT, 
	"DateAdded" TEXT, 
	"Status" TEXT, 
	"AcquisitionIntent" VARCHAR(16), 
	"Type" TEXT, 
	"ComicID" TEXT, 
	"ArtworkURL" TEXT, 
	"ReleaseDate" TEXT, 
	"Location" TEXT, 
	"IssueDate" TEXT, 
	"DigitalDate" TEXT, 
	"Int_IssueNumber" INTEGER, 
	"ComicSize" TEXT, 
	"AltIssueNumber" TEXT, 
	"IssueDate_Edit" TEXT, 
	"ImageURL" TEXT, 
	"ImageURL_ALT" TEXT, 
	forced_file INTEGER, 
	"inCacheDIR" TEXT, 
	"ChapterNumber" TEXT, 
	"VolumeNumber" TEXT, 
	CONSTRAINT uq_issues_issueid UNIQUE ("IssueID")
);
INSERT INTO "issues" VALUES('910001','Starfall Rangers',NULL,'1','2026-01-01','Downloaded','policy',NULL,'900001',NULL,'2026-01-01','Starfall Rangers 001.cbz','2026-01-01',NULL,1000,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "issues" VALUES('910002','Starfall Rangers',NULL,'2','2026-01-01','Wanted','wanted',NULL,'900001',NULL,'2026-01-01',NULL,'2026-01-01',NULL,2000,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "issues" VALUES('910003','Starfall Rangers',NULL,'3','2026-01-01','Snatched','wanted',NULL,'900001',NULL,'2026-01-01',NULL,'2026-01-01',NULL,3000,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "issues" VALUES('910004','Starfall Rangers',NULL,'4','2026-01-01','Failed','wanted',NULL,'900001',NULL,'2026-01-01',NULL,'2026-01-01',NULL,4000,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "issues" VALUES('910005','Harbor Lights',NULL,'1','2026-01-01','Skipped','skipped',NULL,'900002',NULL,'2026-01-01',NULL,'2026-01-01',NULL,1000,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "issues" VALUES('910006','Harbor Lights',NULL,'2','2026-01-01','Ignored','ignored',NULL,'900002',NULL,'2026-01-01',NULL,'2026-01-01',NULL,2000,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "issues" VALUES('910007','The Quiet Engine',NULL,'1','2026-01-01','Archived','policy',NULL,'900003',NULL,'2026-01-01','The Quiet Engine 001.cbr','2026-01-01',NULL,1000,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "issues" VALUES('910008','The Quiet Engine',NULL,'2','2026-01-01','Downloaded','policy',NULL,'900003',NULL,'2026-01-01','The Quiet Engine 002.cbz','2026-01-01',NULL,2000,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "issues" VALUES('md-chapter-910009','Lantern Garden',NULL,'1','2026-01-01','Downloaded','policy',NULL,'md-0f5e1c2a-matrix',NULL,'2026-01-01','Lantern Garden c001.cbz','2026-01-01',NULL,1000,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'1','1');
INSERT INTO "issues" VALUES('md-chapter-910010','Lantern Garden',NULL,'2','2026-01-01','Wanted','wanted',NULL,'md-0f5e1c2a-matrix',NULL,'2026-01-01',NULL,'2026-01-01',NULL,2000,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2','1');
CREATE TABLE jobhistory (
	"JobName" TEXT, 
	prev_run_datetime TEXT, 
	prev_run_timestamp FLOAT, 
	next_run_datetime TEXT, 
	next_run_timestamp FLOAT, 
	last_run_completed TEXT, 
	successful_completions TEXT, 
	failed_completions TEXT, 
	status TEXT, 
	last_success_timestamp FLOAT, 
	last_failure_timestamp FLOAT, 
	last_error TEXT, 
	last_date TEXT, 
	CONSTRAINT uq_jobhistory_jobname UNIQUE ("JobName")
);
CREATE TABLE manualresults (
	provider TEXT, 
	id TEXT, 
	kind TEXT, 
	comicname TEXT, 
	volume TEXT, 
	oneoff TEXT, 
	fullprov TEXT, 
	issuenumber TEXT, 
	modcomicname TEXT, 
	name TEXT, 
	link TEXT, 
	size TEXT, 
	pack_numbers TEXT, 
	pack_issuelist TEXT, 
	comicyear TEXT, 
	issuedate TEXT, 
	tmpprov TEXT, 
	pack TEXT, 
	issueid TEXT, 
	comicid TEXT, 
	sarc TEXT, 
	issuearcid TEXT
);
CREATE TABLE mylar_info (
	"DatabaseVersion" INTEGER NOT NULL, 
	PRIMARY KEY ("DatabaseVersion")
);
INSERT INTO "mylar_info" VALUES(0);
CREATE TABLE notifs (
	session_id INTEGER NOT NULL, 
	date TEXT NOT NULL, 
	event TEXT, 
	comicid TEXT, 
	comicname TEXT, 
	issuenumber TEXT, 
	seriesyear TEXT, 
	status TEXT, 
	message TEXT, 
	PRIMARY KEY (session_id, date)
);
CREATE TABLE nzblog (
	"IssueID" TEXT, 
	"NZBName" TEXT, 
	"SARC" TEXT, 
	"PROVIDER" TEXT, 
	"ID" TEXT, 
	"AltNZBName" TEXT, 
	"OneOff" TEXT, 
	CONSTRAINT uq_nzblog_issueid_provider UNIQUE ("IssueID", "PROVIDER")
);
CREATE TABLE oneoffhistory (
	"ComicName" TEXT, 
	"IssueNumber" TEXT, 
	"ComicID" TEXT, 
	"IssueID" TEXT, 
	"Status" TEXT, 
	weeknumber TEXT, 
	year TEXT, 
	CONSTRAINT uq_oneoffhistory_comicid_issueid UNIQUE ("ComicID", "IssueID")
);
CREATE TABLE pipeline_journal (
	release_key TEXT NOT NULL, 
	issueid TEXT, 
	provider TEXT, 
	downloader_type TEXT, 
	nzbname TEXT, 
	hash TEXT, 
	stage TEXT NOT NULL, 
	stage_rank INTEGER NOT NULL, 
	payload_json TEXT, 
	fail_reason TEXT, 
	updated_date TEXT NOT NULL, 
	status TEXT, 
	retry_count INTEGER, 
	next_retry_at TEXT, 
	CONSTRAINT uq_pipeline_journal_release_key UNIQUE (release_key)
);
CREATE TABLE provider_searches (
	id INTEGER, 
	provider TEXT, 
	type TEXT, 
	lastrun INTEGER, 
	active TEXT, 
	hits INTEGER DEFAULT '0', 
	UNIQUE (id), 
	UNIQUE (provider)
);
CREATE TABLE readlist (
	"IssueID" TEXT, 
	"ComicName" TEXT, 
	"Issue_Number" TEXT, 
	"Status" TEXT, 
	"DateAdded" TEXT, 
	"Location" TEXT, 
	"inCacheDir" TEXT, 
	"SeriesYear" TEXT, 
	"ComicID" TEXT, 
	"StatusChange" TEXT, 
	"IssueDate" TEXT, 
	CONSTRAINT uq_readlist_issueid UNIQUE ("IssueID")
);
CREATE TABLE ref32p (
	"ComicID" TEXT, 
	"ID" TEXT, 
	"Series" TEXT, 
	"Updated" TEXT, 
	UNIQUE ("ComicID")
);
CREATE TABLE rssdb (
	"Title" TEXT, 
	"Link" TEXT, 
	"Pubdate" TEXT, 
	"Site" TEXT, 
	"Size" TEXT, 
	"Issue_Number" TEXT, 
	"ComicName" TEXT, 
	UNIQUE ("Title")
);
CREATE TABLE searchresults (
	"SRID" TEXT, 
	results NUMERIC, 
	"Series" TEXT, 
	publisher TEXT, 
	haveit TEXT, 
	name TEXT, 
	deck TEXT, 
	url TEXT, 
	description TEXT, 
	comicid TEXT, 
	comicimage TEXT, 
	issues TEXT, 
	comicyear TEXT, 
	ogcname TEXT, 
	sresults TEXT
);
CREATE TABLE snatched (
	"IssueID" TEXT, 
	"ComicName" TEXT, 
	"Issue_Number" TEXT, 
	"Size" INTEGER, 
	"DateAdded" TEXT, 
	"Status" TEXT, 
	"FolderName" TEXT, 
	"ComicID" TEXT, 
	"Provider" TEXT, 
	"Hash" TEXT, 
	crc TEXT, 
	CONSTRAINT uq_snatched_issue_status_provider UNIQUE ("IssueID", "Status", "Provider")
);
INSERT INTO "snatched" VALUES('910003','Starfall Rangers','3',41000000,'2026-01-02 10:00:00','Snatched','Starfall.Rangers.003.2019','900001','MatrixNZB','matrixhash0003',NULL);
INSERT INTO "snatched" VALUES('910001','Starfall Rangers','1',40000000,'2026-01-01 10:00:00','Post-Processed','Starfall.Rangers.001.2019','900001','MatrixNZB','matrixhash0001',NULL);
CREATE TABLE storyarcs (
	"StoryArcID" TEXT, 
	"ComicName" TEXT, 
	"IssueNumber" TEXT, 
	"SeriesYear" TEXT, 
	"IssueYEAR" TEXT, 
	"StoryArc" TEXT, 
	"TotalIssues" TEXT, 
	"Status" TEXT, 
	"inCacheDir" TEXT, 
	"Location" TEXT, 
	"IssueArcID" TEXT, 
	"ReadingOrder" INTEGER, 
	"IssueID" TEXT, 
	"ComicID" TEXT, 
	"ReleaseDate" TEXT, 
	"IssueDate" TEXT, 
	"Publisher" TEXT, 
	"IssuePublisher" TEXT, 
	"IssueName" TEXT, 
	"CV_ArcID" TEXT, 
	"Int_IssueNumber" INTEGER, 
	"DynamicComicName" TEXT, 
	"Volume" TEXT, 
	"Manual" TEXT, 
	"DateAdded" TEXT, 
	"DigitalDate" TEXT, 
	"Type" TEXT, 
	"Aliases" TEXT, 
	"ArcImage" TEXT, 
	"StoreDate" TEXT, 
	CONSTRAINT uq_storyarcs_issuearcid UNIQUE ("IssueArcID")
);
INSERT INTO "storyarcs" VALUES('930001','Starfall Rangers','1',NULL,NULL,'The Long Night','2','Downloaded',NULL,'Starfall Rangers 001.cbz','930001_910001',1,'910001','900001',NULL,NULL,'Matrix Press',NULL,NULL,'930001',NULL,NULL,NULL,'added',NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "storyarcs" VALUES('930001','The Quiet Engine','2',NULL,NULL,'The Long Night','2','Wanted',NULL,NULL,'930001_910008',2,'910008','900003',NULL,NULL,'Matrix Press',NULL,NULL,'930001',NULL,NULL,NULL,'added',NULL,NULL,NULL,NULL,NULL,NULL);
CREATE TABLE tmp_searches (
	query_id INTEGER NOT NULL, 
	comicid INTEGER NOT NULL, 
	comicname TEXT, 
	publisher TEXT, 
	publisherimprint TEXT, 
	comicyear TEXT, 
	issues TEXT, 
	volume TEXT, 
	deck TEXT, 
	url TEXT, 
	type TEXT, 
	cvarcid TEXT, 
	arclist TEXT, 
	description TEXT, 
	haveit TEXT, 
	mode TEXT, 
	searchtype TEXT, 
	comicimage TEXT, 
	thumbimage TEXT, 
	PRIMARY KEY (query_id, comicid)
);
CREATE TABLE upcoming (
	"ComicName" TEXT, 
	"IssueNumber" TEXT, 
	"ComicID" TEXT, 
	"IssueID" TEXT, 
	"IssueDate" TEXT, 
	"Status" TEXT, 
	"DisplayComicName" TEXT, 
	CONSTRAINT uq_upcoming_comicid_issuenum UNIQUE ("ComicID", "IssueNumber")
);
CREATE TABLE weekly (
	"SHIPDATE" TEXT, 
	"PUBLISHER" TEXT, 
	"ISSUE" TEXT, 
	"COMIC" VARCHAR(150), 
	"EXTRA" TEXT, 
	"STATUS" TEXT, 
	"ComicID" TEXT, 
	"IssueID" TEXT, 
	"CV_Last_Update" TEXT, 
	"DynamicName" TEXT, 
	weeknumber TEXT, 
	year TEXT, 
	volume TEXT, 
	seriesyear TEXT, 
	annuallink TEXT, 
	format TEXT, 
	rowid INTEGER NOT NULL, 
	PRIMARY KEY (rowid), 
	CONSTRAINT uq_weekly_comicid_issueid UNIQUE ("ComicID", "IssueID")
);
INSERT INTO "weekly" VALUES('2026-01-07','Matrix Press','5','Starfall Rangers',NULL,'Wanted','900001','910011',NULL,NULL,'01','2026',NULL,NULL,NULL,'print',1);
INSERT INTO "weekly" VALUES('2026-01-07','Elsewhere Comics','1','Unwatched Horizon',NULL,'Skipped','999901','999911',NULL,NULL,'01','2026',NULL,NULL,NULL,'print',2);
CREATE INDEX acq_canary_permit_release ON acquisition_canary_permits (release_key);
CREATE INDEX acq_canary_permit_state ON acquisition_canary_permits (state, expires_at);
CREATE INDEX acq_reconciliation_state ON acquisition_reconciliation (state);
CREATE INDEX acq_repair_canary_run ON acquisition_repair_canaries (run_id);
CREATE INDEX acq_repair_events_run ON acquisition_repair_events (run_id, event_id);
CREATE INDEX acq_repair_items_entity ON acquisition_repair_items (entity_type, entity_id);
CREATE INDEX acq_repair_items_run_state ON acquisition_repair_items (run_id, apply_state);
CREATE INDEX acq_repair_manifest_run ON acquisition_repair_manifests (run_id);
CREATE INDEX acq_repair_runs_state ON acquisition_repair_runs (state);
CREATE INDEX acq_repair_series_run_state ON acquisition_repair_series (run_id, state);
CREATE INDEX acq_search_preview_run ON acquisition_search_previews (run_id);
CREATE INDEX acq_search_preview_series_state ON acquisition_search_previews (series_id, state);
CREATE INDEX acquisition_maintenance_events_epoch ON acquisition_maintenance_events (epoch);
CREATE INDEX acquisition_maintenance_leases_active ON acquisition_maintenance_leases (released_at, epoch);
CREATE INDEX acquisition_run_items_entity ON acquisition_run_items (command_kind, entity_type, entity_id);
CREATE INDEX acquisition_run_items_run_state ON acquisition_run_items (run_id, state);
CREATE INDEX acquisition_runs_state ON acquisition_runs (completion_state);
CREATE INDEX ai_activity_entity_id ON ai_activity_log (entity_id);
CREATE INDEX ai_activity_timestamp ON ai_activity_log (timestamp);
CREATE INDEX ai_metadata_entity ON ai_metadata_history (entity_type, entity_id);
CREATE INDEX annuals_acquisition_intent ON annuals ("AcquisitionIntent");
CREATE INDEX annuals_comicid ON annuals ("ComicID");
CREATE INDEX comics_id ON comics ("ComicID");
CREATE INDEX comics_status ON comics ("Status");
CREATE INDEX ddl_info_status_updated ON ddl_info (status, updated_date);
CREATE INDEX failed_issueid ON failed ("IssueID");
CREATE INDEX issues_acquisition_intent ON issues ("AcquisitionIntent");
CREATE INDEX issues_comicid ON issues ("ComicID");
CREATE INDEX issues_comicname ON issues ("ComicName");
CREATE INDEX issues_id ON issues ("IssueID");
CREATE INDEX issues_status ON issues ("Status");
CREATE INDEX issues_status_comicname ON issues ("Status", "ComicName");
CREATE INDEX pipeline_journal_stage ON pipeline_journal (stage);
CREATE INDEX snatched_issueid ON snatched ("IssueID");
CREATE INDEX storyarcs_comicid ON storyarcs ("ComicID");
CREATE INDEX storyarcs_cv_arcid ON storyarcs ("CV_ArcID");
CREATE INDEX storyarcs_status_comicname ON storyarcs ("Status", "ComicName");
CREATE INDEX storyarcs_status_storyarc ON storyarcs ("Status", "StoryArc");
CREATE INDEX storyarcs_storyarcid ON storyarcs ("StoryArcID");
CREATE INDEX upcoming_issuedate ON upcoming ("IssueDate");
CREATE INDEX upcoming_issueid ON upcoming ("IssueID");
CREATE INDEX weekly_comicid ON weekly ("ComicID");
COMMIT;
