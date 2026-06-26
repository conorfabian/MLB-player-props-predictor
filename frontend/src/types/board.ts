export type BoardPick = {
  rank: number;
  player_name: string;
  team: string;
  opponent: string;
  prop_type: string;
  line: number;
  side: string;
  model_probability: number;
  game_time: string | null;
  result_status: string;
  actual_value: number | null;
  graded_at: string | null;
};

export type DailyBoard = {
  slate_date: string;
  generated_at: string;
  model_version: string;
  status: string;
  picks: BoardPick[];
};
