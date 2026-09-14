import { google } from "googleapis";
import { getAuthorizedClient } from "./src/auth.js";

async function analyzeSheet10() {
  console.log("Authenticating...");
  const auth = await getAuthorizedClient();
  const sheets = google.sheets({ version: "v4", auth });

  const spreadsheetId = "1aFB2O37w-Dh0RmN_W2CultjS1X4Vb7LqxbKMb99UVp4";
  
  console.log(`Fetching values from "シート10"...`);
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: "シート10!A1:Z500",
  });

  const rows = res.data.values ?? [];
  console.log(`Total rows fetched: ${rows.length}`);

  // 定義する金額階級 (単位: 円)
  // 例: [0, 200000, 400000, 600000, 800000, 1000000, 1500000, 2000000, Infinity]
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

  // 集計データ構造: { "2026-01": { "20万円未満": count, ... }, ... }
  const stats: Record<string, Record<string, number>> = {};
  const monthsSet = new Set<string>();

  let totalParsed = 0;
  let skipped = 0;

  for (const row of rows) {
    // row[0]: 日付 (例: "2026/03/02")
    // row[1]: IDなど (例: "868733")
    // row[2]: 金額 (例: "798000")
    if (!row || row.length < 3) {
      skipped++;
      continue;
    }
    const dateStr = row[0];
    const amountStr = row[2]?.replace(/,/g, "").trim();

    if (!dateStr || !amountStr) {
      skipped++;
      continue;
    }

    // 月抽出 (YYYY/MM または YYYY-MM)
    const dateMatch = dateStr.match(/^(\d{4})[\/\-](\d{1,2})[\/\-]\d{1,2}$/);
    if (!dateMatch) {
      // 日付フォーマット違いの可能性
      skipped++;
      continue;
    }
    const yearMonth = `${dateMatch[1]}-${dateMatch[2].padStart(2, "0")}`;
    monthsSet.add(yearMonth);

    const amount = Number(amountStr);
    if (isNaN(amount)) {
      skipped++;
      continue;
    }

    // 階級判定
    let matchedBracket = brackets[brackets.length - 1].label;
    for (const b of brackets) {
      if (amount >= b.min && amount < b.max) {
        matchedBracket = b.label;
        break;
      }
    }

    if (!stats[yearMonth]) {
      stats[yearMonth] = {};
      brackets.forEach(b => (stats[yearMonth][b.label] = 0));
    }
    stats[yearMonth][matchedBracket]++;
    totalParsed++;
  }

  const sortedMonths = Array.from(monthsSet).sort();

  console.log(`\n=== データのパース結果 ===`);
  console.log(`有効データ件数: ${totalParsed}, スキップ件数: ${skipped}`);
  console.log(`対象月: ${sortedMonths.join(", ")}`);

  console.log(`\n=== 月別・金額階級別 売上件数分布クロス集計表 ===`);
  // ヘッダー行出力
  const header = ["金額階級", ...sortedMonths].join("\t");
  console.log(header);

  for (const b of brackets) {
    const rowValues = [b.label];
    for (const m of sortedMonths) {
      const count = stats[m]?.[b.label] ?? 0;
      rowValues.push(count.toString());
    }
    console.log(rowValues.join("\t"));
  }

  // 合計行
  const totalRow = ["合計"];
  for (const m of sortedMonths) {
    let monthTotal = 0;
    for (const b of brackets) {
      monthTotal += stats[m]?.[b.label] ?? 0;
    }
    totalRow.push(monthTotal.toString());
  }
  console.log(totalRow.join("\t"));
}

analyzeSheet10().catch(console.error);
