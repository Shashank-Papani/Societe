export type PresenceUserError = {
  title: string;
  body: string;
  code: string;
};

type ApiErrorLike = {
  status: number;
  code: string;
  message: string;
};

function isApiErrorLike(error: unknown): error is ApiErrorLike {
  return (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    "code" in error &&
    "message" in error &&
    typeof (error as ApiErrorLike).status === "number" &&
    typeof (error as ApiErrorLike).code === "string" &&
    typeof (error as ApiErrorLike).message === "string"
  );
}

export function mapPresenceError(error: unknown): PresenceUserError {
  if (isApiErrorLike(error)) {
    const code = error.code.toUpperCase();
    if (code.includes("PERMISSION") || /location access|permission/i.test(error.message)) {
      return {
        title: "Location needed",
        body: "Location access is required to verify that you’re at the venue.",
        code,
      };
    }
    if (
      code.includes("OUTSIDE") ||
      code.includes("TOO_FAR") ||
      /outside|too far|geofence|distance/i.test(error.message)
    ) {
      return {
        title: "Too far away",
        body: "You need to be closer to this venue to verify your presence.",
        code,
      };
    }
    if (error.status === 429 || code.includes("RATE")) {
      return {
        title: "Temporarily unavailable",
        body: "Please wait a moment and try verifying again.",
        code,
      };
    }
    if (error.status >= 500 || code.includes("UNAVAILABLE")) {
      return {
        title: "Verification unavailable",
        body: "We couldn’t verify your presence right now. Try again shortly.",
        code,
      };
    }
    if (error.status === 0 || /network|fetch|connection/i.test(error.message)) {
      return {
        title: "Connection problem",
        body: "We couldn’t verify your presence. Check your connection and try again.",
        code,
      };
    }
  }

  if (error instanceof Error) {
    if (/permission denied|unavailable/i.test(error.message)) {
      return {
        title: "Location needed",
        body: "Location access is required to verify that you’re at the venue.",
        code: "LOCATION_DENIED",
      };
    }
    if (/network|fetch|connection/i.test(error.message)) {
      return {
        title: "Connection problem",
        body: "We couldn’t verify your presence. Check your connection and try again.",
        code: "NETWORK",
      };
    }
  }

  return {
    title: "Couldn’t verify",
    body: "We couldn’t verify your presence. Check your connection and try again.",
    code: "UNKNOWN",
  };
}

/** Map server presence snapshot that stayed outside after submit. */
export function mapOutsidePresenceReasons(reasons: string[]): PresenceUserError {
  const joined = reasons.join(" ").toLowerCase();
  if (joined.includes("outside") || joined.includes("distance") || joined.includes("polygon")) {
    return {
      title: "Too far away",
      body: "You need to be closer to this venue to verify your presence.",
      code: "OUTSIDE",
    };
  }
  if (joined.includes("accuracy")) {
    return {
      title: "Location too imprecise",
      body: "Move closer to the venue and try again with a clearer GPS signal.",
      code: "ACCURACY",
    };
  }
  return {
    title: "Not verified yet",
    body: "Stay near the venue and try verifying again.",
    code: "NOT_VERIFIED",
  };
}
