import { NextResponse } from 'next/server';
import { google } from 'googleapis';
import type { General } from '@/data/generals';

// 四天王（1〜4位）: 仏教における四天王の名を冠する
const TITLES_SHITENNO = ['毘沙門天', '持国天', '増長天', '広目天'];
// 武将（5〜8位）: 個別称号を持つ精鋭
const TITLES_BUSHO = ['大将軍', '丞相', '都督', '猛将'];
// 一兵卒（9位以降）: 人数無制限で増え続ける一般兵
const TITLE_HEISOTSU = '一兵卒';

function resolveTierAndTitle(index: number): { tier: General['tier']; title: string } {
  if (index < TITLES_SHITENNO.length) {
    return { tier: 'shitenno', title: TITLES_SHITENNO[index] };
  }
  if (index < TITLES_SHITENNO.length + TITLES_BUSHO.length) {
    return { tier: 'busho', title: TITLES_BUSHO[index - TITLES_SHITENNO.length] };
  }
  return { tier: 'heisotsu', title: TITLE_HEISOTSU };
}

function toDriveThumbnail(url: string): string {
  const match = url.match(/\/file\/d\/([a-zA-Z0-9_-]+)/);
  if (!match) return url;
  return `https://drive.google.com/thumbnail?id=${match[1]}&sz=w400-h250`;
}

export async function GET() {
  try {
    const auth = new google.auth.GoogleAuth({
      credentials: {
        client_email: process.env.GOOGLE_SERVICE_ACCOUNT_EMAIL,
        private_key: process.env.GOOGLE_PRIVATE_KEY?.replace(/\\n/g, '\n'),
      },
      scopes: ['https://www.googleapis.com/auth/spreadsheets.readonly'],
    });

    const sheets = google.sheets({ version: 'v4', auth });
    const spreadsheetId = '1YMxcM8b3TyOK55GQYHgN0Wa3rfseeNKv2iJFJEJ8fJQ';
    // 行数上限を指定しない（一兵卒が無制限に増えても全件取得できるようにする）
    const range = 'ランキング!A2:E';

    const response = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range,
    });

    const rows = response.data.values || [];
    const validRows = rows.filter((row: string[]) => (row[0] || '').trim().length > 0);

    const generals: General[] = validRows.map((row: string[], index: number) => {
      const { tier, title } = resolveTierAndTitle(index);
      const rawImageUrl = row[4] && row[4].startsWith('http') ? row[4] : '';

      return {
        rank: index + 1,
        name: row[0] || '',
        title,
        tier,
        stats: {
          avgCases: parseFloat(row[1]) || 0,
          bookingRate: parseFloat((row[2] || '').replace('%', '')) || 0,
          avgCalls: parseFloat(row[3]) || 0,
        },
        imageUrl: rawImageUrl
          ? toDriveThumbnail(rawImageUrl)
          : `https://picsum.photos/seed/${encodeURIComponent(row[0] || String(index))}/400/250`,
      };
    });

    return NextResponse.json(generals);
  } catch (error) {
    console.error('Sheets API Error:', error);
    return NextResponse.json({ error: 'Failed to fetch data' }, { status: 500 });
  }
}
