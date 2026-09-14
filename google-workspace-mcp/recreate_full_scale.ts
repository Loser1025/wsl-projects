import { google } from "googleapis";
import { getAuthorizedClient } from "./src/auth.js";

async function recreateFullScaleCrossTab() {
  console.log("Authenticating...");
  const auth = await getAuthorizedClient();
  const sheets = google.sheets({ version: "v4", auth });

  const spreadsheetId = "1aFB2O37w-Dh0RmN_W2CultjS1X4Vb7LqxbKMb99UVp4";
  
  console.log(`Fetching all values from "シート10" (up to 10,000 rows)...`);
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: "シート10!A1:Z10000",
  });

  const rows = res.data.values ?? [];
  console.log(`Total rows fetched: ${rows.length}`);

  // 金額階級の定義
  const brackets = [
    { label: "20万円未満", min: 0, max: 200000 },
    { label: "20万〜40万未満", min: 200000, max: 400000 },
    { label: "40万〜60万未満", min: 400000, max: 600000 },
    { label: "60万〜80万未満", min: 600000, max: 800000 },
    { label: "80万〜100万未満", min: 800000, max: 1000000 },
    { label: "100万〜150万未満", min: 1000000, max: 1500000 },
    { label: "150万〜200万未満", min: 1500000, max: 2000000 },
    { label: "200万円以上", min: 2000000, max: Infinity },
  ];

  // 横軸の期間: 2026-01 から 2026-09
  const months: string[] = [];
  for (let m = 1; m <= 9; m++) {
    months.push(`2026-${String(m).padStart(2, "0")}`);
  }

  // 集計データ構造
  const stats: Record<string, Record<string, number>> = {};
  months.forEach(m => {
    stats[m] = {};
    brackets.forEach(b => {
      stats[m][b.label] = 0;
    });
  });

  let parsedCount = 0;
  let skippedCount = 0;
  let minDateFound: string | null = null;
  let maxDateFound: string | null = null;

  for (const row of rows) {
    if (!row || row.length < 3) {
      skippedCount++;
      continue;
    }
    const dateStr = row[0]?.toString().trim();
    const amountStr = row[2]?.toString().replace(/,/g, "").trim();
    if (!dateStr || !amountStr) {
      skippedCount++;
      continue;
    }

    const dateMatch = dateStr.match(/^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})$/);
    if (!dateMatch) {
      skippedCount++;
      continue;
    }

    const year = dateMatch[1];
    const month = dateMatch[2].padStart(2, "0");
    const day = dateMatch[3].padStart(2, "0");
    const yearMonth = `${year}-${month}`;

    const normalizedDate = `${year}/${month}/${day}`;
    if (!minDateFound || normalizedDate < minDateFound) minDateFound = normalizedDate;
    if (!maxDateFound || normalizedDate > maxDateFound) maxDateFound = normalizedDate;

    if (!months.includes(yearMonth)) {
      skippedCount++;
      continue;
    }

    const amount = Number(amountStr);
    if (isNaN(amount)) {
      skippedCount++;
      continue;
    }

    let matchedBracket = brackets[brackets.length - 1].label;
    for (const b of brackets) {
      if (amount >= b.min && amount < b.max) {
        matchedBracket = b.label;
        break;
      }
    }

    stats[yearMonth][matchedBracket]++;
    parsedCount++;
  }

  console.log(`\n=== スキャン結果 ===`);
  console.log(`検出された最小日付: ${minDateFound}`);
  console.log(`検出された最大日付: ${maxDateFound}`);
  console.log(`期間 2026-01 〜 2026-09 の有効パース件数: ${parsedCount}`);
  console.log(`スキップ／対象外件数: ${skippedCount}`);

  // 書き込み用2次元配列の作成
  const headerRow = ["金額階級 \\ 月", ...months, "総合計"];
  const tableData: (string | number)[][] = [headerRow];

  for (const b of brackets) {
    const rowValues: (string | number)[] = [b.label];
    let rowTotal = 0;
    for (const m of months) {
      const val = stats[m][b.label];
      rowValues.push(val);
      rowTotal += val;
    }
    rowValues.push(rowTotal);
    tableData.push(rowValues);
  }

  // 合計行
  const totalRow: (string | number)[] = ["合計"];
  let grandTotal = 0;
  for (const m of months) {
    let monthTotal = 0;
    for (const b of brackets) {
      monthTotal += stats[m][b.label];
    }
    totalRow.push(monthTotal);
    grandTotal += monthTotal;
  }
  totalRow.push(grandTotal);
  tableData.push(totalRow);

  console.log("\n=== 完全版 拡張クロス集計表 ===");
  tableData.forEach(row => {
    console.log(row.join("\t"));
  });

  // シートの確認と書き込み
  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  const existingSheet = meta.data.sheets?.find(s => s.properties?.title === "月別金額集計");

  let sheetId: number;
  if (!existingSheet) {
    const addRes = await sheets.spreadsheets.batchUpdate({
      spreadsheetId,
      requestBody: {
        requests: [
          {
            addSheet: {
              properties: {
                title: "月別金額集計",
                gridProperties: { rowCount: 30, columnCount: 15 },
              },
            },
          },
        ],
      },
    });
    sheetId = addRes.data.replies?.[0]?.addSheet?.properties?.sheetId ?? 0;
  } else {
    sheetId = existingSheet.properties?.sheetId ?? 0;
    await sheets.spreadsheets.values.clear({
      spreadsheetId,
      range: "月別金額集計!A1:Z50",
    });
  }

  const range = "月別金額集計!A1";
  console.log(`\n書き込み中: ${range}`);
  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range,
    valueInputOption: "USER_ENTERED",
    requestBody: {
      values: tableData,
    },
  });

  console.log("スタイルを適用中...");
  await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [
        {
          repeatCell: {
            range: {
              sheetId: sheetId,
              startRowIndex: 0,
              endRowIndex: 1,
              startColumnIndex: 0,
              endColumnIndex: months.length + 2,
            },
            cell: {
              userEnteredFormat: {
                backgroundColor: { red: 0.2, green: 0.3, blue: 0.5 },
                textFormat: {
                  foregroundColor: { red: 1, green: 1, blue: 1 },
                  bold: true,
                },
                horizontalAlignment: "CENTER",
              },
            },
            fields: "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
          },
        },
        {
          repeatCell: {
            range: {
              sheetId: sheetId,
              startRowIndex: tableData.length - 1,
              endRowIndex: tableData.length,
              startColumnIndex: 0,
              endColumnIndex: months.length + 2,
            },
            cell: {
              userEnteredFormat: {
                backgroundColor: { red: 0.9, green: 0.9, blue: 0.9 },
                textFormat: { bold: true },
              },
            },
            fields: "userEnteredFormat(backgroundColor,textFormat)",
          },
        },
        {
          repeatCell: {
            range: {
              sheetId: sheetId,
              startRowIndex: 1,
              endRowIndex: tableData.length - 1,
              startColumnIndex: 0,
              endColumnIndex: 1,
            },
            cell: {
              userEnteredFormat: {
                textFormat: { bold: true },
                backgroundColor: { red: 0.95, green: 0.95, blue: 0.95 },
              },
            },
            fields: "userEnteredFormat(textFormat,backgroundColor)",
          },
        },
        {
          repeatCell: {
            range: {
              sheetId: sheetId,
              startRowIndex: 1,
              endRowIndex: tableData.length,
              startColumnIndex: 1,
              endColumnIndex: months.length + 2,
            },
            cell: {
              userEnteredFormat: {
                horizontalAlignment: "RIGHT",
                numberFormat: { type: "NUMBER", pattern: "#,##0" },
              },
            },
            fields: "userEnteredFormat(horizontalAlignment,numberFormat)",
          },
        },
      ],
    },
  });

  console.log("全件スキャンによる完全版クロス集計の出力が完了しました！");
}

recreateFullScaleCrossTab().catch(console.error);
