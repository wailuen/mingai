"use client";

import { useState, useMemo } from "react";

/**
 * Common IANA timezone list for the searchable dropdown.
 * Full list would come from Intl.supportedValuesOf('timeZone') in modern browsers.
 */
function getTimezones(): string[] {
  if (typeof Intl !== "undefined" && "supportedValuesOf" in Intl) {
    return (
      Intl as unknown as { supportedValuesOf: (key: string) => string[] }
    ).supportedValuesOf("timeZone");
  }
  // Fallback for older environments
  return [
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Asia/Singapore",
    "Asia/Kolkata",
    "Asia/Dubai",
    "Asia/Kuala_Lumpur",
    "Australia/Sydney",
    "Pacific/Auckland",
  ];
}

interface TimezoneSelectorProps {
  value: string;
  onChange: (tz: string) => void;
}

/**
 * Searchable timezone dropdown with all IANA timezones.
 */
export function TimezoneSelector({ value, onChange }: TimezoneSelectorProps) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const timezones = useMemo(() => getTimezones(), []);

  const filtered = useMemo(
    () =>
      search
        ? timezones.filter((tz) =>
            tz.toLowerCase().includes(search.toLowerCase()),
          )
        : timezones,
    [timezones, search],
  );

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-left text-sm text-text-primary transition-colors focus:border-accent focus:outline-none"
      >
        {value || "Select timezone..."}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1 w-full rounded-card border border-border bg-bg-surface shadow-lg">
            <div className="border-b border-border p-2">
              <input
                type="text"
                placeholder="Search timezones..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                autoFocus
              />
            </div>
            <div className="max-h-48 overflow-y-auto p-1">
              {filtered.length === 0 ? (
                <div className="px-3 py-2 text-sm text-text-faint">
                  No timezones found
                </div>
              ) : (
                filtered.map((tz) => (
                  <button
                    key={tz}
                    onClick={() => {
                      onChange(tz);
                      setOpen(false);
                      setSearch("");
                    }}
                    className={`w-full rounded-control px-3 py-1.5 text-left text-sm transition-colors ${
                      tz === value
                        ? "bg-accent-dim text-accent"
                        : "text-text-muted hover:bg-bg-elevated hover:text-text-primary"
                    }`}
                  >
                    {tz}
                  </button>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
