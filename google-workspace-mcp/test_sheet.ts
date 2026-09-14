import { google } from "googleapis";
import { getAuthorizedClient } from "./src/auth.js";

async function test() {
  console.log("Authenticating...");
  const auth = await getAuthorizedClient();
  const sheets = google.sheets({ version: "v4", auth });

  const spreadsheetId = "1aFB2O37w-Dh0RmN_W2CultjS1X4Vb7LqxbKMb99UVp4";
  
  console.log(`Fetching spreadsheet metadata for ID: ${spreadsheetId}`);
  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  console.log("Spreadsheet Title:", meta.data.properties?.title);
  console.log("Sheets:");
  meta.data.sheets?.forEach(sheet => {
    console.log(` - ${sheet.properties?.title} (ID: ${sheet.properties?.sheetId})`);
  });

  // Try to get values from the first sheet or general range
  const firstSheetName = meta.data.sheets?.[0]?.properties?.title ?? "Sheet1";
  const range = `${firstSheetName}!A1:Z100`;
  console.log(`Fetching values for range: ${range}`);
  
  try {
    const res = await sheets.spreadsheets.values.get({ spreadsheetId, range });
    console.log("Values retrieved successfully:");
    console.log(JSON.stringify(res.data.values, null, 2));
  } catch (err: any) {
    console.error("Error fetching values:", err.message);
  }
}

test().catch(console.error);
