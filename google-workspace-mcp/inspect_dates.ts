import { google } from "googleapis";
import { getAuthorizedClient } from "./src/auth.js";

async function inspectSheet10Dates() {
  console.log("Authenticating...");
  const auth = await getAuthorizedClient();
  const sheets = google.sheets({ version: "v4", auth });

  const spreadsheetId = "1aFB2O37w-Dh0RmN_W2CultjS1X4Vb7LqxbKMb99UVp4";
  
  console.log(`Fetching all values from "シート10"...`);
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: "シート10!A1:Z5000",
  });

  const rows = res.data.values ?? [];
  console.log(`Total rows fetched: ${rows.length}`);

  let minDate: string | null = null;
  let maxDate: string | null = null;
  const dateCounts: Record<string, number> = {};
  const monthCounts: Record<string, number> = {};
  let invalidRows = 0;

  for (const row of rows) {
    if (!row || row.length === 0) continue;
    const dateStr = row[0]?.trim();
    if (!dateStr) {
      invalidRows++;
      continue;
    }

    // 日付フォーマットのチェック (YYYY/MM/DD または YYYY-MM-DD など)
    const match = dateStr.match(/^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})$/);
    if (!match) {
      invalidRows++;
      continue;
    }

    const year = match[1];
    const month = match[2].padStart(2, "0");
    const ym = `${year}-${month}`;
    const normalizedDate = `${year}/${month}/${match[3].padStart(2, "0")}`;

    if (!minDate || normalizedDate < minDate) {
      minDate = normalizedDate;
    }
    if (!maxDate || normalizedDate > maxDate) {
      maxDate = normalizedDate;
    }

    dateCounts[normalizedDate] = (dateCounts[normalizedDate] || 0) + 1;
    monthCounts[ym] = (monthCounts[ym] || 0) + 1;
  }

  console.log(`\n=== 調査結果 ===`);
  console.log(`最小日付: ${minDate}`);
  console.log(`最大日付: ${maxDate}`);
  console.log(`日付なし・無効行数: ${invalidRows}`);
  
  console.log(`\n=== 月別のデータ件数 ===`);
  const sortedMonths = Object.keys(monthCounts).sort();
  for (const ym of sortedMonths) {
    console.log(`  ${ym}: ${monthCounts[ym]} 件`);
  }
}

inspectSheet10Dates().catch(console.error);
