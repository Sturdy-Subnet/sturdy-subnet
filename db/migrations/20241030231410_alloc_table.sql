-- migrate:up

CREATE TABLE IF NOT EXISTS allocation_requests (
    request_uid TEXT PRIMARY KEY,
    assets_and_pools TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE active_allocs (
    request_uid TEXT PRIMARY KEY,
    scoring_period_end TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (request_uid) REFERENCES allocation_requests (request_uid)
);

CREATE TABLE IF NOT EXISTS allocations (
    request_uid TEXT,
    miner_uid TEXT,
    allocation TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (request_uid, miner_uid),
    FOREIGN KEY (request_uid) REFERENCES allocation_requests (request_uid)
);

-- This alter statement adds a new column to the allocations table if it exists
ALTER TABLE allocation_requests
ADD COLUMN request_type TEXT NOT NULL DEFAULT 1;
ALTER TABLE allocation_requests
ADD COLUMN metadata TEXT;
ALTER TABLE allocations
ADD COLUMN axon_time FLOAT NOT NULL DEFAULT 99999.0; -- large number for now

-- migrate:down

DROP TABLE IF EXISTS fulfilled_allocs;
DROP TABLE IF EXISTS allocations;
DROP TABLE IF EXISTS allocation_requests;
