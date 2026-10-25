CREATE TABLE access_requests (
 id TEXT PRIMARY KEY, legal_name TEXT NOT NULL, registration_number TEXT NOT NULL,
 registration_jurisdiction TEXT NOT NULL, organization_domain TEXT NOT NULL,
 work_email TEXT NOT NULL, applicant_name TEXT NOT NULL, use_case TEXT NOT NULL,
 uei TEXT, cage TEXT, status TEXT NOT NULL DEFAULT 'pending_review' CHECK(status IN ('pending_review','approved','rejected')),
 claim_hash TEXT NOT NULL, domain_challenge TEXT NOT NULL, domain_verified_at TEXT,
 aup_version TEXT NOT NULL, aup_hash TEXT NOT NULL, aup_text TEXT NOT NULL, accepted_at TEXT NOT NULL,
 attestation_receipt TEXT NOT NULL, approved_at TEXT, reviewer TEXT, entity_evidence TEXT,
 authorization_evidence TEXT, claimed_at TEXT, created_at TEXT NOT NULL
);
CREATE INDEX access_requests_status ON access_requests(status,created_at);
CREATE TABLE api_keys (
 id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE REFERENCES access_requests(id),
 key_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE audit_events (
 id TEXT PRIMARY KEY, request_id TEXT REFERENCES access_requests(id), key_id TEXT,
 event TEXT NOT NULL, asset_id TEXT, receipt TEXT, evidence TEXT, created_at TEXT NOT NULL
);
CREATE INDEX audit_request ON audit_events(request_id,created_at);
