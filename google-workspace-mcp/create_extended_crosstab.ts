import { google } from "googleapis";
import { getAuthorizedClient } from "./src/auth.js";

async function createExtendedCrossTab() {
  console.log("Authenticating...");
  const auth = await getAuthorizedClient();
  const sheets = google.sheets({ version: "v4", auth });

  const spreadsheetId = "1aFB2O37w-Dh0RmN_W2CultjS1X4Vb7LqxbKMb99UVp4";
  
  console.log(`Fetching values from "シート10"...`);
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: "シート10!A1:Z1000",
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

  // 集計データ構造: { "2026-01": { "20万円未満": count, ... }, ... }
  const stats: Record<string, Record<string, number>> = {};
  months.forEach(m => {
    stats[m] = {};
    brackets.forEach(b => {
      stats[m][b.label] = 0;
    });
  });

  for (const row of rows) {
    if (!row || row.length < 3) continue;
    const dateStr = row[0];
    const amountStr = row[2]?.replace(/,/g, "").trim();
    if (!dateStr || !amountStr) continue;

    const dateMatch = dateStr.match(/^(\d{4})[\/\-](\d{1,2})[\/\-]\d{1,2}$/);
    if (!dateMatch) continue;
    const yearMonth = `${dateMatch[1]}-${dateMatch[2].padStart(2, "0")}`;

    if (!months.includes(yearMonth)) continue; // 対象外の月はスキップ

    const amount = Number(amountStr);
    if (isNaN(amount)) continue;

    let matchedBracket = brackets[brackets.length - 1].label;
    for (const b of brackets) {
      if (amount >= b.min && amount < b.max) {
        matchedBracket = b.label;
        break;
      }
    }

    stats[yearMonth][matchedBracket]++;
  }

  // 書き込み用2次元配列の作成
  // ヘッダー行: ["金額階級 / 月", "2026-01", "2026-02", ..., "2026-09", "合計"]
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

  console.log("\n=== 拡張クロス集計表 (コンソール表示) ===");
  tableData.forEach(row => {
    console.log(row.join("\t"));
  });

  // スプレッドシート側の書き込み先として、新しいシート「月別金額集計」を作成するか確認・追加
  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  const existingSheet = meta.data.sheets?.find(s => s.properties?.title === "月別金額集計");

  let sheetId: number;
  if (!existingSheet) {
    console.log('\n新しいシート "月別金額集計" を作成します...');
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
    console.log('\n既存のシート "月別金額集計" を利用して上書きします...');
  }

  // 値の書き込み (E列やF1あたりに綺麗に配置、あるいはA1から)
  const range = "月別金額集計!A1";
  console.log(`書き込み中: ${range}`);
  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range,
    valueInputOption: "USER_ENTERED",
    requestBody: {
      values: tableData,
    },
  });

  // 見栄えを良くするための装飾 (バッチアップデート: タイトル行の背景色、太字、ボーダーなど)
  console.log("表のスタイルを装飾中...");
  await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [
        // ヘッダー行の背景色設定 (ダークブルー / 白抜き文字・太字)
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
        // 合計行の背景色設定 (薄いグレー・太字)
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
        // 縦見出し列 (金額階級) の太字・中央揃え
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
        // 数値部分の右揃えとカンマなどのフォーマット
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

  console.log("完了しました！スプレッドシート「月別金額集計」に綺麗な拡張クロス集計表が出力されました。");
}

createExtendedCrossTab().catch(console.error);
