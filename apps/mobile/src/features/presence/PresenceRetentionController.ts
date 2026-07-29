/**
 * Global presence retention controller (one instance per authenticated app).
 *
 * Foreground: 3-minute heartbeat + 30 m movement trigger.
 * Background: best-effort via TaskManager (separate module).
 */

import {
  FOREGROUND_HEARTBEAT_SECONDS,
  MOVEMENT_TRIGGER_METERS,
  MOVEMENT_TRIGGER_THROTTLE_SECONDS,
} from "@/features/presence/presenceRetentionPolicy";
import {
  haversineMeters,
  shouldStartRetention,
  shouldTriggerMovementHeartbeat,
} from "@/features/presence/presenceRetention";
import { submitRetentionHeartbeat } from "@/features/presence/PresenceHeartbeatService";
import type { PresenceSnapshot } from "@/features/presence/api";
import {
  getLocationProvider,
  type ForegroundLocationSample,
} from "@/location/LocationProvider";

export { shouldStartRetention, shouldTriggerMovementHeartbeat };

export type RetentionControllerCallbacks = {
  onPresenceUpdated: (snapshot: PresenceSnapshot) => void;
  getActivePresence: () => PresenceSnapshot | null;
};

type ControllerState = {
  running: boolean;
  appForeground: boolean;
  inFlight: boolean;
  lastSubmittedAtMs: number;
  lastSubmittedSample: ForegroundLocationSample | null;
  latestSample: ForegroundLocationSample | null;
  intervalId: ReturnType<typeof setInterval> | null;
  watchGeneration: number;
};

const ACCURACY_MAX_M = 50;

export class PresenceRetentionController {
  private readonly callbacks: RetentionControllerCallbacks;
  private state: ControllerState = {
    running: false,
    appForeground: true,
    inFlight: false,
    lastSubmittedAtMs: 0,
    lastSubmittedSample: null,
    latestSample: null,
    intervalId: null,
    watchGeneration: 0,
  };

  constructor(callbacks: RetentionControllerCallbacks) {
    this.callbacks = callbacks;
  }

  start(): void {
    if (this.state.running) {
      return;
    }
    this.state.running = true;
    this.state.watchGeneration += 1;
    this.ensureInterval();
    void this.pollLatestSample();
  }

  stop(): void {
    this.state.running = false;
    this.clearInterval();
    this.state.latestSample = null;
    this.state.lastSubmittedSample = null;
    this.state.lastSubmittedAtMs = 0;
    this.state.inFlight = false;
  }

  setAppForeground(foreground: boolean): void {
    const wasBackground = !this.state.appForeground;
    this.state.appForeground = foreground;
    if (!this.state.running) {
      return;
    }
    if (foreground) {
      this.ensureInterval();
      if (wasBackground) {
        void this.heartbeatNow({ reason: "foreground" });
      }
    } else {
      this.clearInterval();
    }
  }

  /** Called when presence query updates — start/stop based on active lease. */
  syncPresence(presence: PresenceSnapshot | null): void {
    const active =
      presence != null &&
      (presence.state === "verified" ||
        presence.state === "rechecking" ||
        presence.state === "degraded") &&
      Boolean(presence.venue?.id);

    if (active && !this.state.running) {
      this.start();
      void this.heartbeatNow({ reason: "presence_start" });
      return;
    }
    if (!active && this.state.running) {
      this.stop();
    }
  }

  noteLocationSample(sample: ForegroundLocationSample): void {
    if (!this.state.running || !this.state.appForeground) {
      return;
    }
    if (
      !Number.isFinite(sample.horizontal_accuracy_m) ||
      sample.horizontal_accuracy_m > ACCURACY_MAX_M
    ) {
      return;
    }
    this.state.latestSample = sample;
    if (!this.state.lastSubmittedSample) {
      return;
    }
    const moved = haversineMeters(this.state.lastSubmittedSample, sample);
    const sinceLast = (Date.now() - this.state.lastSubmittedAtMs) / 1000;
    if (
      shouldTriggerMovementHeartbeat({
        movedMeters: moved,
        secondsSinceLastSubmit: sinceLast,
        accuracyMeters: sample.horizontal_accuracy_m,
        maxAccuracyMeters: ACCURACY_MAX_M,
        movementMeters: MOVEMENT_TRIGGER_METERS,
        throttleSeconds: MOVEMENT_TRIGGER_THROTTLE_SECONDS,
      })
    ) {
      void this.heartbeatNow({ reason: "movement", sample });
    }
  }

  async heartbeatNow(options?: {
    reason?: string;
    sample?: ForegroundLocationSample;
  }): Promise<PresenceSnapshot | null> {
    if (!this.state.running || this.state.inFlight) {
      return null;
    }
    const presence = this.callbacks.getActivePresence();
    if (
      !presence?.venue?.id ||
      (presence.state !== "verified" &&
        presence.state !== "rechecking" &&
        presence.state !== "degraded")
    ) {
      return null;
    }

    this.state.inFlight = true;
    const generation = this.state.watchGeneration;
    try {
      let sample = options?.sample ?? this.state.latestSample;
      if (!sample) {
        sample = await getLocationProvider().getCurrentSample();
      }
      if (!sample) {
        return null;
      }
      // Stale real-location must not overwrite an active __DEV__ fixture.
      const live = await getLocationProvider().getCurrentSample();
      if (live) {
        sample = live;
      }

      const snapshot = await submitRetentionHeartbeat({
        sample,
        venueId: presence.venue.id,
        appState: this.state.appForeground ? "foreground" : "background",
      });
      if (!snapshot || generation !== this.state.watchGeneration) {
        return null;
      }
      this.state.lastSubmittedAtMs = Date.now();
      this.state.lastSubmittedSample = sample;
      this.state.latestSample = sample;
      this.callbacks.onPresenceUpdated(snapshot);
      return snapshot;
    } catch {
      return null;
    } finally {
      this.state.inFlight = false;
    }
  }

  /** Test helpers */
  getDebug(): Readonly<ControllerState> {
    return this.state;
  }

  private ensureInterval(): void {
    if (this.state.intervalId || !this.state.appForeground) {
      return;
    }
    this.state.intervalId = setInterval(() => {
      void this.heartbeatNow({ reason: "interval" });
    }, FOREGROUND_HEARTBEAT_SECONDS * 1000);
  }

  private clearInterval(): void {
    if (this.state.intervalId) {
      clearInterval(this.state.intervalId);
      this.state.intervalId = null;
    }
  }

  private async pollLatestSample(): Promise<void> {
    if (!this.state.running || !this.state.appForeground) {
      return;
    }
    try {
      const sample = await getLocationProvider().getCurrentSample();
      if (sample) {
        this.noteLocationSample(sample);
      }
    } catch {
      // ignore
    }
  }
}

