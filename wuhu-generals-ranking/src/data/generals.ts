export interface GeneralStats {
  avgCases: number;    // アベ受任
  bookingRate: number; // 予約率（%）
  avgCalls: number;    // アベコール数
}

export interface General {
  rank: number;
  name: string;
  title: string;
  team: 'A' | 'B';
  stats: GeneralStats;
  imageUrl: string;
}
