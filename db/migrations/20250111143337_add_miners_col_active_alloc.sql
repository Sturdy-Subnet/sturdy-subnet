-- migrate:up
ALTER TABLE active_allocs
ADD COLUMN miners TEXT;
-- migrate:down
ALTER TABLE active_allocs DROP COLUMN miner_uids TEXT;