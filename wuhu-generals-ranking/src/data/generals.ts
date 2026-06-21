export interface GeneralStats {
  military: number;    // 武力
  intelligence: number; // 智力
  leadership: number;   // 統率
}

export interface General {
  rank: number;
  name: string;
  title: string;
  team: 'A' | 'B';
  stats: GeneralStats;
  avatar?: string;
  imageUrl: string;
}

export const mockGenerals: General[] = [
  {
    rank: 1,
    name: "関羽",
    title: "大将軍",
    team: 'A',
    stats: { military: 97, intelligence: 75, leadership: 90 },
    imageUrl: "https://picsum.photos/seed/guanyu/400/250",
  },
  {
    rank: 2,
    name: "諸葛亮",
    title: "丞相",
    team: 'A',
    stats: { military: 38, intelligence: 100, leadership: 95 },
    imageUrl: "https://picsum.photos/seed/zhuge/400/250",
  },
  {
    rank: 3,
    name: "周瑜",
    title: "都督",
    team: 'A',
    stats: { military: 71, intelligence: 96, leadership: 93 },
    imageUrl: "https://picsum.photos/seed/zhouyu/400/250",
  },
  {
    rank: 4,
    name: "張飛",
    title: "一兵卒",
    team: 'B',
    stats: { military: 98, intelligence: 30, leadership: 70 },
    imageUrl: "https://picsum.photos/seed/zhangfei/400/250",
  },
  {
    rank: 5,
    name: "趙雲",
    title: "一兵卒",
    team: 'B',
    stats: { military: 96, intelligence: 65, leadership: 85 },
    imageUrl: "https://picsum.photos/seed/zhaoyun/400/250",
  },
  {
    rank: 6,
    name: "馬超",
    title: "一兵卒",
    team: 'B',
    stats: { military: 97, intelligence: 45, leadership: 75 },
    imageUrl: "https://picsum.photos/seed/machao/400/250",
  },
];

/**
 * Google Sheets API から武将データを取得する（スタブ）
 * 将来的に Google Sheets API からデータを取得する想定。
 * 現時点ではモックデータを返す。
 */
export async function fetchGeneralsFromSheet(): Promise<General[]> {
  // TODO: Google Sheets API 連携
  // const SHEET_ID = process.env.NEXT_PUBLIC_GOOGLE_SHEET_ID;
  // const API_KEY = process.env.NEXT_PUBLIC_GOOGLE_API_KEY;
  // const res = await fetch(
  //   `https://sheets.googleapis.com/v4/spreadsheets/${SHEET_ID}/values/Sheet1?key=${API_KEY}`
  // );
  // const data = await res.json();
  // return parseSheetData(data);
  return mockGenerals;
}
