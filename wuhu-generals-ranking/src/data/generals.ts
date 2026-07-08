export interface GeneralStats {
  avgCases: number;    // アベ受任
  bookingRate: number; // 予約率（%）
  avgCalls: number;    // アベコール数
}

export type GeneralTier = 'shitenno' | 'busho' | 'heisotsu';

export interface General {
  rank: number;
  name: string;
  title: string;
  tier: GeneralTier;
  stats: GeneralStats;
  imageUrl: string;
}
