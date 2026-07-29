/**
 * Local-only saved venues (favorites). Replaceable by a future backend endpoint.
 * Persists venue ids via expo-file-system — not synced across devices.
 */

import * as FileSystem from "expo-file-system/legacy";
import { useCallback, useEffect, useState } from "react";

import {
  isVenueSaved,
  toggleSavedVenueId,
} from "@/features/discover/savedVenuesHelpers";

const FILE_NAME = "societe-saved-venues.json";

type SavedVenuesFile = {
  venueIds: string[];
};

function fileUri(): string {
  const root = FileSystem.documentDirectory;
  if (!root) {
    throw new Error("documentDirectory unavailable");
  }
  return `${root}${FILE_NAME}`;
}

export async function loadSavedVenueIds(): Promise<string[]> {
  try {
    const uri = fileUri();
    const info = await FileSystem.getInfoAsync(uri);
    if (!info.exists) {
      return [];
    }
    const raw = await FileSystem.readAsStringAsync(uri);
    const parsed = JSON.parse(raw) as SavedVenuesFile;
    if (!Array.isArray(parsed.venueIds)) {
      return [];
    }
    return parsed.venueIds.filter((id): id is string => typeof id === "string" && id.length > 0);
  } catch {
    return [];
  }
}

export async function persistSavedVenueIds(venueIds: string[]): Promise<void> {
  const uri = fileUri();
  const payload: SavedVenuesFile = { venueIds: [...new Set(venueIds)] };
  await FileSystem.writeAsStringAsync(uri, JSON.stringify(payload));
}

export { isVenueSaved, toggleSavedVenueId } from "@/features/discover/savedVenuesHelpers";

export function useSavedVenues() {
  const [ids, setIds] = useState<string[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let mounted = true;
    void loadSavedVenueIds().then((loaded) => {
      if (mounted) {
        setIds(loaded);
        setReady(true);
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  const toggle = useCallback(async (venueId: string) => {
    let previous: string[] = [];
    let next: string[] = [];
    setIds((current) => {
      previous = current;
      next = toggleSavedVenueId(current, venueId);
      return next;
    });
    try {
      await persistSavedVenueIds(next);
    } catch {
      setIds(previous);
    }
  }, []);

  return {
    ready,
    savedIds: ids,
    isSaved: (venueId: string) => isVenueSaved(ids, venueId),
    toggleSaved: toggle,
  };
}
