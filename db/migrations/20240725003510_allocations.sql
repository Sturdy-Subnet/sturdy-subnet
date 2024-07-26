-- migrate:up

CREATE TABLE allocation_requests (
    request_uid TEXT PRIMARY KEY,
    assets_and_pools TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE allocations (
  request_uid TEXT,
  miner_uid TEXT,
  allocation TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (request_uid, miner_uid),
  FOREIGN KEY (request_uid) REFERENCES allocation_requests (request_uid)
);

-- migrate:down

DROP TABLE allocation_requests;
DROP TABLE allocations;
