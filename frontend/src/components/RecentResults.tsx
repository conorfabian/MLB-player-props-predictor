"use client";

import { useEffect, useState } from "react";

import type { RecentResults as RecentResultsData } from "@/types/performance";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

export function RecentResults() {
  const [results, setResults] = useState<RecentResultsData | null>(null);
  const [error, setError] = useState<string | null>(
    apiBaseUrl ? null : "API base URL is not configured.",
  );

  useEffect(() => {
    if (!apiBaseUrl) {
      return;
    }

    async function loadResults() {
      try {
        const response = await fetch(
          `${apiBaseUrl}/api/results/recent`,
          {
            cache: "no-store",
          },
        );

        if (!response.ok) {
          throw new Error(
            `Recent results request failed with status ${response.status}`,
          );
        }

        const data: RecentResultsData = await response.json();
        setResults(data);
      } catch (requestError) {
        const message =
          requestError instanceof Error
            ? requestError.message
            : "Unknown request error";

        setError(message);
      }
    }

    void loadResults();
  }, []);

  if (error) {
    return (
      <section className="mt-10 rounded-lg border border-red-300 p-6">
        <h2 className="text-2xl font-semibold">Recent Results</h2>
        <p className="mt-2 text-red-700">{error}</p>
      </section>
    );
  }

  if (!results) {
    return (
      <section className="mt-10 rounded-lg border p-6">
        <h2 className="text-2xl font-semibold">Recent Results</h2>
        <p className="mt-2 text-gray-500">Loading recent results...</p>
      </section>
    );
  }

  return (
    <section className="mt-10">
      <h2 className="text-2xl font-semibold">Recent Results</h2>

      {results.boards.length === 0 ? (
        <p className="mt-3 text-gray-600">
          No published boards were found.
        </p>
      ) : (
        <div className="mt-4 space-y-5">
          {results.boards.map((board) => (
            <article
              key={board.slate_date}
              className="rounded-lg border p-5"
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h3 className="text-xl font-semibold">
                    {board.slate_date}
                  </h3>
                  <p className="mt-1 text-sm text-gray-500">
                    Model: {board.model_version}
                  </p>
                </div>

                <p className="text-sm text-gray-600">
                  Hit rate: {formatRate(board.summary.hit_rate)}
                </p>
              </div>

              <div className="mt-4 flex flex-wrap gap-3 text-sm text-gray-600">
                <span>Hits: {board.summary.hits}</span>
                <span>Misses: {board.summary.misses}</span>
                <span>Pushes: {board.summary.pushes}</span>
                <span>Pending: {board.summary.pending}</span>
              </div>

              <div className="mt-4 divide-y">
                {board.picks.map((pick) => (
                  <div
                    key={`${board.slate_date}-${pick.rank}`}
                    className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div>
                      <p className="font-medium">
                        #{pick.rank} {pick.player_name}
                      </p>
                      <p className="text-sm text-gray-500">
                        {pick.side.toUpperCase()} {pick.line}{" "}
                        {pick.prop_type}
                      </p>
                    </div>

                    <p className="text-sm text-gray-600">
                      {pick.result_status.toUpperCase()}
                      {pick.actual_value !== null
                        ? ` · Actual hits: ${pick.actual_value}`
                        : ""}
                    </p>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function formatRate(value: number | null) {
  if (value === null) {
    return "N/A";
  }

  return `${(value * 100).toFixed(1)}%`;
}
