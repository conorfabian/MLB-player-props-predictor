"use client";

import { useEffect, useState } from "react";

type HealthResponse = {
  status: string;
  service: string;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

export function ApiStatus() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(
    apiBaseUrl ? null : "NEXT_PUBLIC_API_BASE_URL is not configured.",
  );

  useEffect(() => {
    if (!apiBaseUrl) {
      return;
    }

    async function loadHealth() {
      try {
        const response = await fetch(`${apiBaseUrl}/health`);

        if (!response.ok) {
          throw new Error(`API returned status ${response.status}`);
        }

        const data: HealthResponse = await response.json();
        setHealth(data);
      } catch (requestError) {
        const message =
          requestError instanceof Error
            ? requestError.message
            : "Unknown API error";

        setError(message);
      }
    }

    void loadHealth();
  }, []);

  if (error) {
    return (
      <p className="mt-4 text-red-700">
        Backend connection failed: {error}
      </p>
    );
  }

  if (!health) {
    return <p className="mt-4 text-gray-500">Checking backend...</p>;
  }

  return (
    <p className="mt-4 text-green-700">
      Backend connected: {health.service}
    </p>
  );
}
