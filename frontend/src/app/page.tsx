import { ApiStatus } from "@/components/ApiStatus";

export default function Home() {
  return (
    <main className="mx-auto min-h-screen max-w-5xl px-6 py-12">
      <h1 className="text-3xl font-bold">MLB Props Predictor</h1>

      <p className="mt-3 text-gray-600">
        Daily model-ranked MLB player props.
      </p>

      <ApiStatus />

      <section className="mt-8 rounded-lg border p-6">
        <h2 className="text-xl font-semibold">Today&apos;s Board</h2>
        <p className="mt-2 text-gray-500">
          Waiting for database connection.
        </p>
      </section>
    </main>
  );
}
