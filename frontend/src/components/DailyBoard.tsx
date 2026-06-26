"use client";

import { useEffect, useState } from "react";

import type { DailyBoard as DailyBoardData } from "@/types/board";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

export function DailyBoard() {
  const [board, setBoard] = useState<DailyBoardData | null>(null);
  const [error, setError] = useState<string | null>(
    apiBaseUrl ? null : "API base URL is not configured.",
  );

  useEffect(() => {
    if (!apiBaseUrl) {
      return;
    }

    async function loadBoard() {
      try {
        const response = await fetch(
          `${apiBaseUrl}/api/boards/latest`,
          {
            cache: "no-store",
          },
        );

        if (!response.ok) {
          throw new Error(
            `Board request failed with status ${response.status}`,
          );
        }

        const data: DailyBoardData = await response.json();
        setBoard(data);
      } catch (requestError) {
        const message =
          requestError instanceof Error
            ? requestError.message
            : "Unknown request error";

        setError(message);
      }
    }

    void loadBoard();
  }, []);

  if (error) {
    return (
      <section className="mt-8 rounded-lg border border-red-300 p-6">
        <h2 className="text-xl font-semibold">Today&apos;s Board</h2>
        <p className="mt-2 text-red-700">{error}</p>
      </section>
    );
  }

  if (!board) {
    return (
      <section className="mt-8 rounded-lg border p-6">
        <h2 className="text-xl font-semibold">Today&apos;s Board</h2>
        <p className="mt-2 text-gray-500">Loading board...</p>
      </section>
    );
  }

  return (
    <section className="mt-8">
      <div className="mb-4">
        <h2 className="text-2xl font-semibold">Today&apos;s Board</h2>

        <p className="mt-1 text-sm text-gray-500">
          Slate: {board.slate_date} · Model: {board.model_version}
        </p>
      </div>

      <div className="space-y-4">
        {board.picks.map((pick) => (
          <article
            key={pick.rank}
            className="rounded-lg border p-5"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-gray-500">
                  Rank #{pick.rank}
                </p>

                <h3 className="mt-1 text-xl font-semibold">
                  {pick.player_name}
                </h3>

                <p className="mt-1 text-gray-600">
                  {pick.team} vs. {pick.opponent}
                </p>

                <p className="mt-2">
                  {pick.side.toUpperCase()} {pick.line}{" "}
                  {pick.prop_type}
                </p>

                <p className="mt-2 text-sm text-gray-500">
                  Result: {pick.result_status.toUpperCase()}
                  {pick.actual_value !== null
                    ? ` · Actual hits: ${pick.actual_value}`
                    : ""}
                </p>
              </div>

              <div className="text-right">
                <p className="text-sm text-gray-500">
                  Model probability
                </p>

                <p className="mt-1 text-2xl font-bold">
                  {(pick.model_probability * 100).toFixed(1)}%
                </p>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
