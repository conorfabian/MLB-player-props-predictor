import { ApiStatus } from "@/components/ApiStatus";
import { DailyBoard } from "@/components/DailyBoard";

export default function Home() {
  return (
    <main className="mx-auto min-h-screen max-w-5xl px-6 py-12">
      <h1 className="text-3xl font-bold">MLB Props Predictor</h1>

      <p className="mt-3 text-gray-600">
        Daily model-ranked MLB player props.
      </p>

      <ApiStatus />
      <DailyBoard />
    </main>
  );
}
