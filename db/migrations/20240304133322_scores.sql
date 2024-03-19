-- migrate:up

CREATE TABLE api_keys (
    key TEXT PRIMARY KEY,
    name TEXT,
    balance REAL,
    rate_limit_per_minute INTEGER DEFAULT 60,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE logs (
    key TEXT,
    endpoint TEXT,
    cost REAL,
    balance REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(key) REFERENCES api_keys(key) ON DELETE CASCADE
);

-- migrate:down

DROP TABLE api_keys;
DROP TABLE logs;
