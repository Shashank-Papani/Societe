-- Atomic presence lease update.
--
-- KEYS:
--   1 presence:user:{user_id}                       HASH
--   2 presence:venue:{new_venue_id}:active          ZSET
--   3 presence:venue:{new_venue_id}:discoverable    ZSET
--   4 presence:venue:{old_venue_id}:active          ZSET (== KEYS[2] when unchanged)
--   5 presence:venue:{old_venue_id}:discoverable    ZSET (== KEYS[3] when unchanged)
--   6 presence:lease_expirations                    ZSET
--
-- ARGV:
--   1 venue_id            7 discoverable          13 next_transition_epoch
--   2 check_in_id         8 verified_until_epoch
--   3 state               9 grace_until_epoch
--   4 confidence         10 hash_ttl_seconds
--   5 verification_level 11 user_id
--   6 ghost_mode         12 lease_version
--
-- Returns { prior_venue_id, prior_state }.

local user_key = KEYS[1]
local new_active = KEYS[2]
local new_discoverable = KEYS[3]
local old_active = KEYS[4]
local old_discoverable = KEYS[5]
local expirations = KEYS[6]

local venue_id = ARGV[1]
local check_in_id = ARGV[2]
local state = ARGV[3]
local confidence = ARGV[4]
local verification_level = ARGV[5]
local ghost_mode = ARGV[6]
local discoverable = ARGV[7]
local verified_until = tonumber(ARGV[8])
local grace_until = tonumber(ARGV[9])
local hash_ttl = tonumber(ARGV[10])
local user_id = ARGV[11]
local lease_version = ARGV[12]
local next_transition = tonumber(ARGV[13])

local prior_venue = redis.call("HGET", user_key, "venue_id")
local prior_state = redis.call("HGET", user_key, "state")

if old_active ~= new_active then
  redis.call("ZREM", old_active, user_id)
end
if old_discoverable ~= new_discoverable then
  redis.call("ZREM", old_discoverable, user_id)
end

redis.call("HSET", user_key,
  "user_id", user_id,
  "venue_id", venue_id,
  "check_in_id", check_in_id,
  "state", state,
  "confidence", confidence,
  "verification_level", verification_level,
  "ghost_mode", ghost_mode,
  "discoverable", discoverable,
  "verified_until_epoch", verified_until,
  "grace_until_epoch", grace_until,
  -- lease_expires_epoch mirrors grace_until: the hash survives degradation so
  -- the client keeps a stable identity while it retries.
  "lease_expires_epoch", grace_until,
  "lease_version", lease_version
)
redis.call("EXPIRE", user_key, hash_ttl)

-- Active membership tracks the durable presence window (through grace).
redis.call("ZADD", new_active, grace_until, user_id)

-- Discoverability is the strict subset: verified, not ghosted, opted in, and it
-- expires with the verified lease rather than the grace window.
if ghost_mode == "false" and discoverable == "true" and state == "verified" then
  redis.call("ZADD", new_discoverable, verified_until, user_id)
else
  redis.call("ZREM", new_discoverable, user_id)
end

redis.call("ZADD", expirations, next_transition, user_id)

local now = tonumber(redis.call("TIME")[1])
redis.call("ZREMRANGEBYSCORE", new_active, "-inf", now)
redis.call("ZREMRANGEBYSCORE", new_discoverable, "-inf", now)
if old_active ~= new_active then
  redis.call("ZREMRANGEBYSCORE", old_active, "-inf", now)
end
if old_discoverable ~= new_discoverable then
  redis.call("ZREMRANGEBYSCORE", old_discoverable, "-inf", now)
end

return { prior_venue or "", prior_state or "" }
