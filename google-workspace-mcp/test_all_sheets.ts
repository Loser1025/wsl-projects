import { google } from "googleapis";
import { getAuthorizedClient } from "./src/auth.js";

async function testAllSheets() {
  console.log("Authenticating...");
  const auth = await getAuthorizedClient();
  const sheets = google.sheets({ version: "v4", auth });

  const spreadsheetId = "1aFB2O37w-Dh0RmN_W2CultjS1X4Vb7LqxbKMb99UVp4";
  
  console.log(`Fetching spreadsheet metadata for ID: ${spreadsheetId}`);
  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  console.log("Spreadsheet Title:", meta.data.properties?.title);
  
  const sheetList = meta.data.sheets ?? [];
  console.log(`\n--- 全シート一覧 (計 ${sheetList.length} 件) ---`);
  sheetList.forEach((sheet, idx) => {
    console.log(`${idx + 1}. タイトル: "${sheet.properties?.title}" (ID: ${sheet.properties?.sheetId})`);
  });

  // 「シート10」または10番目のシートを探す
  let targetSheet = sheetList.find(s => s.properties?.title === "シート10");
  if (!targetSheet && sheetList.length >= 10) {
    targetSheet = sheetList[9]; // 0-indexed 9th = 10th sheet
  }

  if (targetSheet && targetSheet.properties?.title) {
    const sheetName = targetSheet.properties.title;
    console.log(`\n--- "${sheetName}" のデータを取得 ---`);
    const range = `${sheetName}!A1:Z100`;
    try {
      const res = await sheets.spreadsheets.values.get({ spreadsheetId, range });
      console.log("Values retrieved successfully:");
      console.log(JSON.stringify(res.data.values, null, 2));
    } catch (err: any) {
      console.error(`Error fetching values for ${sheetName}:`, err.message);
    }
  } else {
    console.log("\n「シート10」および10番目のシートは見つかりませんでした。");
  }
}

testAllSheets().catch(console.error);
