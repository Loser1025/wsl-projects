import { NextResponse } from 'next/server';
import { google } from 'googleapis';
import type { General } from '@/data/generals';

const TITLES_TEAM_A = ['大将軍', '丞相', '都督'];
const TITLE_TEAM_B = '一兵卒';

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
    const range = 'ランキング!A2:E15';

    const response = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range,
    });

    const rows = response.data.values || [];
    const validRows = rows.filter((row: string[]) => (row[0] || '').trim().length > 0);

    const generals: General[] = validRows.map((row: string[], index: number) => {
      const team = index < 3 ? 'A' : 'B';
      const rawImageUrl = row[4] && row[4].startsWith('http') ? row[4] : '';

      return {
        rank: index + 1,
        name: row[0] || '',
        title: team === 'A' ? TITLES_TEAM_A[index] : TITLE_TEAM_B,
        team,
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
