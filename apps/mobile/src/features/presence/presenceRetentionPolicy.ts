/**
 * Client-side mirrors of server PresencePolicy defaults.
 * Server remains authoritative for eligibility and lease math.
 */

export const ENTRY_RADIUS_METERS = 160.9344;
export const RETENTION_RADIUS_METERS = 241.4016;
export const FOREGROUND_HEARTBEAT_SECONDS = 180;
export const MOVEMENT_TRIGGER_METERS = 30;
export const MOVEMENT_TRIGGER_THROTTLE_SECONDS = 45;
export const BACKGROUND_HEARTBEAT_SECONDS = 600;
export const BACKGROUND_DISTANCE_INTERVAL_METERS = 50;
export const PRESENCE_LEASE_SECONDS = 1800;
export const PRESENCE_GRACE_SECONDS = 900;

export const PRESENCE_BACKGROUND_LOCATION_TASK = "societe-presence-background-location";
export const PRESENCE_GEOFENCE_TASK = "societe-presence-geofence";
