"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";

interface IssueHeatmapProps {
  data: Array<{ date: string; count: number }>;
  className?: string;
}

const DAY_LABELS = ["S", "M", "T", "W", "T", "F", "S"];

function getCellColor(count: number): string {
  if (count === 0) return "bg-bg-elevated";
  if (count <= 2) return "bg-warn-dim";
  if (count <= 5) return "bg-warn";
  return "bg-alert";
}

function getCellTextColor(count: number): string {
  if (count === 0) return "text-text-faint";
  if (count <= 2) return "text-warn";
  if (count <= 5) return "text-bg-base";
  return "text-bg-base";
}

function formatTooltipDate(dateStr: string): string {
  try {
    return new Date(dateStr + "T00:00:00").toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  } catch {
    return dateStr;
  }
}

function getMonthLabel(dateStr: string): string {
  try {
    return new Date(dateStr + "T00:00:00").toLocaleDateString("en-US", {
      month: "short",
    });
  } catch {
    return "";
  }
}

export function IssueHeatmap({ data, className }: IssueHeatmapProps) {
  const [tooltip, setTooltip] = useState<{
    date: string;
    count: number;
    x: number;
    y: number;
  } | null>(null);

  const { grid, weeks, monthHeaders } = useMemo(() => {
    const countMap = new Map<string, number>();
    for (const d of data) {
      countMap.set(d.date, d.count);
    }

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const totalDays = 56;

    const startDate = new Date(today);
    startDate.setDate(startDate.getDate() - totalDays + 1);

    const startDayOfWeek = startDate.getDay();
    const days: Array<{ date: string; count: number; dayOfWeek: number }> = [];

    for (let i = 0; i < totalDays; i++) {
      const d = new Date(startDate);
      d.setDate(d.getDate() + i);
      const iso = d.toISOString().split("T")[0];
      days.push({
        date: iso,
        count: countMap.get(iso) ?? 0,
        dayOfWeek: d.getDay(),
      });
    }

    const weekColumns: Array<
      Array<{ date: string; count: number; dayOfWeek: number } | null>
    > = [];
    let currentWeek: Array<{
      date: string;
      count: number;
      dayOfWeek: number;
    } | null> = Array.from({ length: 7 }, () => null);

    for (const day of days) {
      currentWeek[day.dayOfWeek] = day;
      if (day.dayOfWeek === 6) {
        weekColumns.push(currentWeek);
        currentWeek = Array.from({ length: 7 }, () => null);
      }
    }

    const hasContent = currentWeek.some((d) => d !== null);
    if (hasContent) {
      weekColumns.push(currentWeek);
    }

    const headers: Array<{ label: string; colIndex: number }> = [];
    let lastMonth = "";

    for (let w = 0; w < weekColumns.length; w++) {
      const firstDay = weekColumns[w].find((d) => d !== null);
      if (firstDay) {
        const month = getMonthLabel(firstDay.date);
        if (month !== lastMonth) {
          headers.push({ label: month, colIndex: w });
          lastMonth = month;
        }
      }
    }

    return { grid: days, weeks: weekColumns, monthHeaders: headers };
  }, [data]);

  function handleMouseEnter(
    e: React.MouseEvent,
    date: string,
    count: number,
  ) {
    const rect = (e.target as HTMLElement).getBoundingClientRect();
    setTooltip({
      date,
      count,
      x: rect.left + rect.width / 2,
      y: rect.top - 8,
    });
  }

  function handleMouseLeave() {
    setTooltip(null);
  }

  return (
    <div className={cn("relative", className)}>
      {/* Month headers */}
      <div className="mb-1 flex gap-0" style={{ paddingLeft: "24px" }}>
        {monthHeaders.map((header) => (
          <span
            key={`${header.label}-${header.colIndex}`}
            className="font-mono text-[10px] text-text-faint"
            style={{
              position: "absolute",
              left: `${24 + header.colIndex * 18}px`,
            }}
          >
            {header.label}
          </span>
        ))}
      </div>

      <div className="mt-4 flex gap-1">
        {/* Day labels */}
        <div className="flex flex-col gap-[3px]">
          {DAY_LABELS.map((label, i) => (
            <div
              key={i}
              className="flex h-[14px] w-[18px] items-center justify-center font-mono text-[10px] text-text-faint"
            >
              {i % 2 === 1 ? label : ""}
            </div>
          ))}
        </div>

        {/* Grid */}
        <div className="flex gap-[3px]">
          {weeks.map((week, wi) => (
            <div key={wi} className="flex flex-col gap-[3px]">
              {week.map((day, di) => (
                <div
                  key={di}
                  onMouseEnter={
                    day
                      ? (e) => handleMouseEnter(e, day.date, day.count)
                      : undefined
                  }
                  onMouseLeave={handleMouseLeave}
                  className={cn(
                    "h-[14px] w-[14px] rounded-[2px] transition-colors",
                    day ? getCellColor(day.count) : "bg-transparent",
                    day && "cursor-pointer hover:ring-1 hover:ring-accent-ring",
                  )}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="mt-3 flex items-center gap-1.5">
        <span className="font-mono text-[10px] text-text-faint">Less</span>
        <div className="h-[10px] w-[10px] rounded-[2px] bg-bg-elevated" />
        <div className="h-[10px] w-[10px] rounded-[2px] bg-warn-dim" />
        <div className="h-[10px] w-[10px] rounded-[2px] bg-warn" />
        <div className="h-[10px] w-[10px] rounded-[2px] bg-alert" />
        <span className="font-mono text-[10px] text-text-faint">More</span>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="pointer-events-none fixed z-50 rounded-control border border-border bg-bg-surface px-2.5 py-1.5 shadow-md"
          style={{
            left: `${tooltip.x}px`,
            top: `${tooltip.y}px`,
            transform: "translate(-50%, -100%)",
          }}
        >
          <p className="font-mono text-[11px] text-text-primary">
            {tooltip.count} issue{tooltip.count !== 1 ? "s" : ""}
          </p>
          <p className="font-mono text-[10px] text-text-faint">
            {formatTooltipDate(tooltip.date)}
          </p>
        </div>
      )}
    </div>
  );
}
