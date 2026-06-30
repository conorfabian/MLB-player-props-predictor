import type { BoardPick } from "@/types/board";

export type PerformanceDateRange = {
  start_date: string | null;
  end_date: string | null;
};

export type RequestedPerformanceWindow = {
  start_date: string;
  end_date: string;
  days: number;
  limit_slates: number | null;
};

export type TopKPerformance = {
  top_1_hit_rate: number | null;
  top_3_hit_rate: number | null;
  top_5_hit_rate: number | null;
  top_10_hit_rate: number | null;
};

export type RankPerformance = {
  rank: number;
  hits: number;
  misses: number;
  pushes: number;
  hit_rate: number | null;
};

export type PerformanceSummary = {
  requested_window: RequestedPerformanceWindow;
  data_date_range: PerformanceDateRange;
  total_slates: number;
  graded_slates: number;
  total_picks: number;
  settled_picks: number;
  decision_picks: number;
  hits: number;
  misses: number;
  pushes: number;
  pending: number;
  postponed: number;
  canceled: number;
  hit_rate: number | null;
  top_k: TopKPerformance;
  by_rank: RankPerformance[];
  latest_graded_slate_date: string | null;
  model_versions: string[];
};

export type RecentBoardSummary = {
  hits: number;
  misses: number;
  pushes: number;
  pending: number;
  decision_picks: number;
  hit_rate: number | null;
};

export type RecentResultBoard = {
  slate_date: string;
  model_version: string;
  status: string;
  picks: BoardPick[];
  summary: RecentBoardSummary;
};

export type RecentResults = {
  boards: RecentResultBoard[];
};
