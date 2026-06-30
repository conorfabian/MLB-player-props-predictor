"use client";

import { useEffect, useState } from "react";

import type { PerformanceSummary as PerformanceSummaryData } from "@/types/performance";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

export function PerformanceSummary() {
  const [summary, setSummary] = useState<PerformanceSummaryData | null>(null);
  const [error, setError] = useState<string | null>(
    apiBaseUrl ? null : "API base URL is not configured.",
  );

  useEffect(() => {
    if (!apiBaseUrl) {
      return;
    }

    async function loadSummary() {
      try {
        const response = await fetch(
          `${apiBaseUrl}/api/performance/summary`,
          {
            cache: "no-store",
          },
        );

        if (!response.ok) {
          throw new Error(
            `Performance request failed with status ${response.status}`,
          );
        }

        const data: PerformanceSummaryData = await response.json();
        setSummary(data);
      } catch (requestError) {
        const message =
          requestError instanceof Error
            ? requestError.message
            : "Unknown request error";

        setError(message);
      }
    }

    void loadSummary();
  }, []);

  if (error) {
    return (
      <section className="mt-10 rounded-lg border border-red-300 p-6">
        <h2 className="text-2xl font-semibold">Performance Summary</h2>
        <p className="mt-2 text-red-700">{error}</p>
      </section>
    );
  }

  if (!summary) {
    return (
      <section className="mt-10 rounded-lg border p-6">
        <h2 className="text-2xl font-semibold">Performance Summary</h2>
        <p className="mt-2 text-gray-500">Loading performance...</p>
      </section>
    );
  }

  const noBoards = summary.total_slates === 0;
  const noGradedSlates = summary.total_slates > 0 && summary.graded_slates === 0;

  return (
    <section className="mt-10 rounded-lg border p-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold">Performance Summary</h2>
          <p className="mt-1 text-sm text-gray-500">
            Last {summary.requested_window.days} days
            {summary.data_date_range.start_date &&
            summary.data_date_range.end_date
              ? ` · Boards ${summary.data_date_range.start_date} to ${summary.data_date_range.end_date}`
              : ""}
          </p>
        </div>

        <p className="text-sm text-gray-500">
          Latest graded slate:{" "}
          {summary.latest_graded_slate_date ?? "N/A"}
        </p>
      </div>

      {noBoards ? (
        <p className="mt-4 text-gray-600">
          No published boards were found in this window.
        </p>
      ) : noGradedSlates ? (
        <p className="mt-4 text-gray-600">
          Published boards exist, but no graded slates are available yet.
        </p>
      ) : null}

      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label="Graded slates"
          value={`${summary.graded_slates} / ${summary.total_slates}`}
        />
        <MetricCard
          label="Decisions"
          value={summary.decision_picks.toString()}
        />
        <MetricCard
          label="Hit rate"
          value={formatRate(summary.hit_rate)}
        />
        <MetricCard
          label="Top-10 hit rate"
          value={formatRate(summary.top_k.top_10_hit_rate)}
        />
      </div>

      <div className="mt-5 flex flex-wrap gap-3 text-sm text-gray-600">
        <span>Hits: {summary.hits}</span>
        <span>Misses: {summary.misses}</span>
        <span>Pushes: {summary.pushes}</span>
        <span>Pending: {summary.pending}</span>
      </div>

      <p className="mt-3 text-sm text-gray-500">
        Model versions:{" "}
        {summary.model_versions.length > 0
          ? summary.model_versions.join(", ")
          : "N/A"}
      </p>
    </section>
  );
}

function MetricCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}

function formatRate(value: number | null) {
  if (value === null) {
    return "N/A";
  }

  return `${(value * 100).toFixed(1)}%`;
}
