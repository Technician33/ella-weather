"use client";

import { useEffect, useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

type Location = {
  id: number;
  slug: string;
  name: string;
  latitude: number;
  longitude: number;
  timezone: string;
};

type ForecastValue = {
  target_time: string;
  issued_at: string;
  temperature_c: number | null;
  precipitation_mm: number | null;
  precipitation_probability: number | null;
  wind_speed_kmh: number | null;
  wind_direction_deg: number | null;
  cloud_cover_pct: number | null;
  relative_humidity_pct: number | null;
  weather_code: number | null;
};

function formatHour(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Home() {
  const [locations, setLocations] = useState<Location[] | null>(null);
  const [locationsError, setLocationsError] = useState<string | null>(null);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);

  const [forecast, setForecast] = useState<ForecastValue[] | null>(null);
  const [forecastError, setForecastError] = useState<string | null>(null);
  // The slug that `forecast`/`forecastError` currently reflect. Deriving
  // "loading" from this (rather than a separate setState call at the top of
  // the effect) keeps every setState call inside an async callback, not
  // synchronous in the effect body - see react-hooks/set-state-in-effect.
  const [loadedSlug, setLoadedSlug] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/locations")
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load locations (${res.status})`);
        return res.json() as Promise<Location[]>;
      })
      .then((data) => {
        setLocations(data);
        if (data.length > 0) setSelectedSlug(data[0].slug);
      })
      .catch((err: Error) => setLocationsError(err.message));
  }, []);

  useEffect(() => {
    if (!selectedSlug) return;

    let cancelled = false;

    fetch(`/api/locations/${selectedSlug}/forecast/current`)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load forecast (${res.status})`);
        return res.json() as Promise<ForecastValue[]>;
      })
      .then((data) => {
        if (cancelled) return;
        setForecast(data);
        setForecastError(null);
        setLoadedSlug(selectedSlug);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setForecast(null);
        setForecastError(err.message);
        setLoadedSlug(selectedSlug);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedSlug]);

  const selectedName = locations?.find((l) => l.slug === selectedSlug)?.name;
  const forecastLoading = selectedSlug !== null && loadedSlug !== selectedSlug;

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <h1 className="text-2xl font-semibold">Ella Weather</h1>

      <div className="flex items-center gap-3">
        <span className="text-sm text-muted-foreground">Location</span>
        {locationsError ? (
          <p className="text-sm text-destructive">{locationsError}</p>
        ) : !locations ? (
          <Skeleton className="h-9 w-48" />
        ) : (
          <Select
            value={selectedSlug ?? undefined}
            onValueChange={(value) => setSelectedSlug(value)}
          >
            <SelectTrigger className="w-48">
              <SelectValue placeholder="Select a city" />
            </SelectTrigger>
            <SelectContent>
              {locations.map((loc) => (
                <SelectItem key={loc.slug} value={loc.slug}>
                  {loc.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            Current forecast{selectedName ? ` — ${selectedName}` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {forecastError ? (
            <p className="text-sm text-destructive">{forecastError}</p>
          ) : forecastLoading || !forecast ? (
            <div className="space-y-2">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-full" />
            </div>
          ) : forecast.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No forecast data yet for this location.
            </p>
          ) : (
            <div className="max-h-[32rem] overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Time</TableHead>
                    <TableHead className="text-right">Temp (°C)</TableHead>
                    <TableHead className="text-right">Precip (mm)</TableHead>
                    <TableHead className="text-right">Precip prob.</TableHead>
                    <TableHead className="text-right">Wind (km/h)</TableHead>
                    <TableHead className="text-right">Cloud cover</TableHead>
                    <TableHead className="text-right">Humidity</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {forecast.map((row) => (
                    <TableRow key={row.target_time}>
                      <TableCell>{formatHour(row.target_time)}</TableCell>
                      <TableCell className="text-right">
                        {row.temperature_c ?? "–"}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.precipitation_mm ?? "–"}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.precipitation_probability ?? "–"}%
                      </TableCell>
                      <TableCell className="text-right">
                        {row.wind_speed_kmh ?? "–"}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.cloud_cover_pct ?? "–"}%
                      </TableCell>
                      <TableCell className="text-right">
                        {row.relative_humidity_pct ?? "–"}%
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
