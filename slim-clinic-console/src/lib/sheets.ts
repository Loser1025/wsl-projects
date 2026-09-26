import { google } from "googleapis";

export const RESERVATION_SHEET_NAMES = ["国内", "韓国", "台湾"] as const;
export type ReservationSheetName = typeof RESERVATION_SHEET_NAMES[number];

export type ReservationRecord = {
  sheetName: ReservationSheetName;
  rowNumber: number;
  values: Record<string, string>;
};

function getSheetsClient() {
  const auth = new google.auth.JWT({
    email: process.env.GOOGLE_SERVICE_ACCOUNT_EMAIL,
    key: (process.env.GOOGLE_SERVICE_ACCOUNT_KEY || "").replace(/\\n/g, "\n"),
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth });
}

function columnIndexToA1(index: number): string {
  let temp = index + 1;
  let letter = "";
  while (temp > 0) {
    const rem = (temp - 1) % 26;
    letter = String.fromCharCode(65 + rem) + letter;
    temp = Math.floor((temp - 1) / 26);
  }
  return letter;
}

async function getHeaderRow(sheetName: ReservationSheetName): Promise<string[]> {
  const sheets = getSheetsClient();
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${sheetName}!1:1`,
  });
  const rows = res.data.values;
  if (!rows || rows.length === 0) return [];
  return rows[0].map(String);
}

async function ensureStatusColumns(sheetName: ReservationSheetName): Promise<void> {
  const headers = await getHeaderRow(sheetName);
  const needed = ["ステータス", "確定日時", "Meetリンク"];
  const missing = needed.filter((col) => !headers.includes(col));
  if (missing.length === 0) return;

  const sheets = getSheetsClient();
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;
  const newHeaders = [...headers, ...missing];
  const endCol = columnIndexToA1(newHeaders.length - 1);
  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range: `${sheetName}!A1:${endCol}1`,
    valueInputOption: "USER_ENTERED",
    requestBody: {
      values: [newHeaders],
    },
  });
}

export async function listPendingReservations(): Promise<ReservationRecord[]> {
  const records: ReservationRecord[] = [];
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;

  for (const sheetName of RESERVATION_SHEET_NAMES) {
    await ensureStatusColumns(sheetName);
    const sheets = getSheetsClient();
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${sheetName}!A:ZZ`,
    });
    const rows = res.data.values;
    if (!rows || rows.length <= 1) continue;

    const headers = rows[0].map(String);
    const statusIndex = headers.indexOf("ステータス");

    for (let i = 1; i < rows.length; i++) {
      const row = rows[i];
      const rowNumber = i + 1;
      const values: Record<string, string> = {};
      for (let j = 0; j < headers.length; j++) {
        const headerName = headers[j];
        if (headerName) {
          values[headerName] = row && row[j] !== undefined && row[j] !== null ? String(row[j]) : "";
        }
      }

      const status = statusIndex >= 0 && row && row[statusIndex] !== undefined && row[statusIndex] !== null ? String(row[statusIndex]).trim() : "";
      if (status === "" || status === "未確定") {
        records.push({
          sheetName,
          rowNumber,
          values,
        });
      }
    }
  }

  return records;
}

export async function confirmReservation(
  sheetName: ReservationSheetName,
  rowNumber: number,
  confirmedDateTime: string,
  meetLink: string
): Promise<void> {
  await ensureStatusColumns(sheetName);
  const headers = await getHeaderRow(sheetName);
  const statusIdx = headers.indexOf("ステータス");
  const confirmedAtIdx = headers.indexOf("確定日時");
  const meetLinkIdx = headers.indexOf("Meetリンク");

  if (statusIdx === -1 || confirmedAtIdx === -1 || meetLinkIdx === -1) {
    throw new Error("Required status columns not found");
  }

  const sheets = getSheetsClient();
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;

  const startCol = Math.min(statusIdx, confirmedAtIdx, meetLinkIdx);
  const endCol = Math.max(statusIdx, confirmedAtIdx, meetLinkIdx);
  const startColA1 = columnIndexToA1(startCol);
  const endColA1 = columnIndexToA1(endCol);

  const rowData: string[] = [];
  for (let j = startCol; j <= endCol; j++) {
    const colName = headers[j];
    if (colName === "ステータス") rowData.push("確定");
    else if (colName === "確定日時") rowData.push(confirmedDateTime);
    else if (colName === "Meetリンク") rowData.push(meetLink);
    else rowData.push("");
  }

  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range: `${sheetName}!${startColA1}${rowNumber}:${endColA1}${rowNumber}`,
    valueInputOption: "USER_ENTERED",
    requestBody: {
      values: [rowData],
    },
  });
}

export async function cancelReservation(sheetName: ReservationSheetName, rowNumber: number): Promise<void> {
  await ensureStatusColumns(sheetName);
  const headers = await getHeaderRow(sheetName);
  const statusIdx = headers.indexOf("ステータス");
  if (statusIdx === -1) {
    throw new Error("Status column not found");
  }

  const sheets = getSheetsClient();
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;
  const colA1 = columnIndexToA1(statusIdx);

  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range: `${sheetName}!${colA1}${rowNumber}`,
    valueInputOption: "USER_ENTERED",
    requestBody: {
      values: [["キャンセル"]],
    },
  });
}
