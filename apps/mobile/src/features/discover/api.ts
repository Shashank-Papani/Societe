import { z } from "zod";

import { apiFetch } from "@/api/client";
import { getLiveAccessToken } from "@/auth/AuthProvider";

const venueCardSchema = z.object({
  id: z.string(),
  slug: z.string(),
  name: z.string(),
  category: z.string(),
  price_band: z.number().nullable().optional(),
  music_tags: z.array(z.string()),
  experience_tags: z.array(z.string()),
  minimum_age: z.number().nullable().optional(),
  city: z.string(),
  region: z.string().nullable().optional(),
  map_pin: z.object({
    latitude: z.number(),
    longitude: z.number(),
  }),
  distance_m: z.number().optional(),
  // Optional future / extended map fields — never invent client-side.
  is_open: z.boolean().nullable().optional(),
  packed_percent: z.number().nullable().optional(),
  crowd_label: z.string().nullable().optional(),
});

const mapResponseSchema = z.object({
  items: z.array(venueCardSchema),
  next_cursor: z.string().nullable(),
});

const venueDetailSchema = z.object({
  id: z.string(),
  slug: z.string(),
  name: z.string(),
  description: z.string().nullable().optional(),
  category: z.string(),
  status: z.string(),
  street_address: z.string().nullable().optional(),
  city: z.string(),
  region: z.string().nullable().optional(),
  country_code: z.string(),
  timezone: z.string(),
  minimum_age: z.number().nullable().optional(),
  price_band: z.number().nullable().optional(),
  music_tags: z.array(z.string()),
  experience_tags: z.array(z.string()),
  centroid: z.object({
    latitude: z.number(),
    longitude: z.number(),
  }),
  hours: z.array(
    z.object({
      weekday: z.number(),
      opens_local: z.string(),
      closes_local: z.string(),
      closes_next_day: z.boolean(),
    }),
  ),
});

export type VenueCard = z.infer<typeof venueCardSchema>;
export type VenueDetail = z.infer<typeof venueDetailSchema>;

async function authHeaders(): Promise<HeadersInit> {
  const token = getLiveAccessToken();
  if (!token) {
    throw new Error("Not signed in");
  }
  return { Authorization: `Bearer ${token}` };
}

export type MapVenuesParams = {
  latitude: number;
  longitude: number;
  radius_m?: number;
  cursor?: string | null;
  limit?: number;
  music_tags?: string[];
  categories?: string[];
  price_bands?: number[];
  minimum_age?: number;
};

export async function fetchMapVenues(params: MapVenuesParams): Promise<z.infer<typeof mapResponseSchema>> {
  const query = new URLSearchParams();
  query.set("latitude", String(params.latitude));
  query.set("longitude", String(params.longitude));
  query.set("radius_m", String(params.radius_m ?? 5000));
  query.set("limit", String(params.limit ?? 20));
  if (params.cursor) {
    query.set("cursor", params.cursor);
  }
  for (const tag of params.music_tags ?? []) {
    query.append("music_tags", tag);
  }
  for (const category of params.categories ?? []) {
    query.append("categories", category);
  }
  for (const band of params.price_bands ?? []) {
    query.append("price_bands", String(band));
  }
  if (params.minimum_age != null) {
    query.set("minimum_age", String(params.minimum_age));
  }

  const envelope = await apiFetch<z.infer<typeof mapResponseSchema>>(`/v1/map/venues?${query}`, {
    headers: await authHeaders(),
  });
  return mapResponseSchema.parse(envelope.data);
}

export async function fetchVenueDetail(venueId: string): Promise<VenueDetail> {
  const envelope = await apiFetch<VenueDetail>(`/v1/venues/${venueId}`, {
    headers: await authHeaders(),
  });
  return venueDetailSchema.parse(envelope.data);
}
