import { google } from "googleapis";
import { RESERVATION_SHEET_NAMES, ReservationSheetName, ReservationRecord } from "@/lib/reservation-fields";

export type { ReservationSheetName, ReservationRecord, Candidate } from "@/lib/reservation-fields";
export {
  RESERVATION_SHEET_NAMES,
  QUESTIONNAIRE_URL_MAP,
  getCustomerName,
  getCustomerEmail,
  getMenuSummary,
  getCandidates,
  getConfirmedDateTime,
  getMeetLink,
  getReminderSentFlag,
  parseConfirmedDateTime,
} from "@/lib/reservation-fields";

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

async function ensureStatusColumns(sheetName: ReservationSheetName, knownHeaders?: string[]): Promise<void> {
  const headers = knownHeaders ?? (await getHeaderRow(sheetName));
  const needed = ["ステータス", "確定日時", "Meetリンク", "スタッフ備考", "リマインド送信済み"];
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

async function fetchAllReservations(): Promise<ReservationRecord[]> {
  const records: ReservationRecord[] = [];
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;
  const sheets = getSheetsClient();

  for (const sheetName of RESERVATION_SHEET_NAMES) {
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${sheetName}!A:ZZ`,
    });
    const rows = res.data.values;
    if (!rows || rows.length === 0) continue;

    const headers = rows[0].map(String);
    await ensureStatusColumns(sheetName, headers);
    if (rows.length <= 1) continue;

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
      records.push({ sheetName, rowNumber, values });
    }
  }

  return records;
}

export async function listAllReservationsGrouped(): Promise<{
  pending: ReservationRecord[];
  confirmed: ReservationRecord[];
}> {
  const all = await fetchAllReservations();
  const pending: ReservationRecord[] = [];
  const confirmed: ReservationRecord[] = [];

  for (const record of all) {
    const status = (record.values["ステータス"] || "").trim();
    if (status === "" || status === "未確定") pending.push(record);
    else if (status === "確定") confirmed.push(record);
  }

  return { pending, confirmed };
}

export async function listPendingReservations(): Promise<ReservationRecord[]> {
  return (await listAllReservationsGrouped()).pending;
}

export async function listConfirmedReservations(): Promise<ReservationRecord[]> {
  return (await listAllReservationsGrouped()).confirmed;
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

export async function rescheduleReservation(
  sheetName: ReservationSheetName,
  rowNumber: number,
  newDateTime: string
): Promise<void> {
  await ensureStatusColumns(sheetName);
  const headers = await getHeaderRow(sheetName);
  const confirmedAtIdx = headers.indexOf("確定日時");
  const reminderIdx = headers.indexOf("リマインド送信済み");
  if (confirmedAtIdx === -1 || reminderIdx === -1) {
    throw new Error("Required columns not found");
  }

  const sheets = getSheetsClient();
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;

  // 確定日時とリマインド送信済みは隣接していない場合があるため、
  // 他の列(Meetリンク等)を巻き込まないよう1セルずつ更新する
  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range: `${sheetName}!${columnIndexToA1(confirmedAtIdx)}${rowNumber}`,
    valueInputOption: "USER_ENTERED",
    requestBody: { values: [[newDateTime]] },
  });

  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range: `${sheetName}!${columnIndexToA1(reminderIdx)}${rowNumber}`,
    valueInputOption: "USER_ENTERED",
    requestBody: { values: [[""]] },
  });
}

export async function markNoShow(sheetName: ReservationSheetName, rowNumber: number): Promise<void> {
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
      values: [["無断キャンセル"]],
    },
  });
}

function normalizePhone(value: string): string {
  return value.replace(/[^\d]/g, "");
}

export async function findJpReservationRowByContact(
  email: string,
  phone: string
): Promise<number | null> {
  const sheetName: ReservationSheetName = "国内";
  await ensureStatusColumns(sheetName);
  const sheets = getSheetsClient();
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${sheetName}!A:ZZ`,
  });
  const rows = res.data.values;
  if (!rows || rows.length <= 1) return null;

  const headers = rows[0].map(String);
  const emailIdx = headers.indexOf("メールアドレス");
  const phoneIdx = headers.indexOf("お電話番号");
  const normalizedEmail = email.trim().toLowerCase();
  const normalizedPhone = normalizePhone(phone);

  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    if (!row) continue;
    const rowEmail = emailIdx >= 0 ? String(row[emailIdx] || "").trim().toLowerCase() : "";
    const rowPhone = phoneIdx >= 0 ? normalizePhone(String(row[phoneIdx] || "")) : "";

    if (normalizedEmail && rowEmail && rowEmail === normalizedEmail) return i + 1;
    if (normalizedPhone && rowPhone && rowPhone === normalizedPhone) return i + 1;
  }
  return null;
}

export async function setJpLineFriendId(rowNumber: number, friendId: string): Promise<void> {
  const sheetName: ReservationSheetName = "国内";
  const headers = await getHeaderRow(sheetName);
  let idx = headers.indexOf("LINE Friend ID");

  const sheets = getSheetsClient();
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;

  if (idx === -1) {
    idx = headers.length;
    const newHeaders = [...headers, "LINE Friend ID"];
    const endCol = columnIndexToA1(newHeaders.length - 1);
    await sheets.spreadsheets.values.update({
      spreadsheetId,
      range: `${sheetName}!A1:${endCol}1`,
      valueInputOption: "USER_ENTERED",
      requestBody: { values: [newHeaders] },
    });
  }

  const colA1 = columnIndexToA1(idx);
  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range: `${sheetName}!${colA1}${rowNumber}`,
    valueInputOption: "USER_ENTERED",
    requestBody: { values: [[friendId]] },
  });
}

export async function getJpLineFriendId(rowNumber: number): Promise<string> {
  const sheetName: ReservationSheetName = "国内";
  const headers = await getHeaderRow(sheetName);
  const idx = headers.indexOf("LINE Friend ID");
  if (idx === -1) return "";

  const sheets = getSheetsClient();
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;
  const colA1 = columnIndexToA1(idx);
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${sheetName}!${colA1}${rowNumber}`,
  });
  return res.data.values?.[0]?.[0] ? String(res.data.values[0][0]) : "";
}

export async function markReminderSent(sheetName: ReservationSheetName, rowNumber: number): Promise<void> {
  await ensureStatusColumns(sheetName);
  const headers = await getHeaderRow(sheetName);
  const idx = headers.indexOf("リマインド送信済み");
  if (idx === -1) {
    throw new Error("Reminder column not found");
  }

  const sheets = getSheetsClient();
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;
  const colA1 = columnIndexToA1(idx);

  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range: `${sheetName}!${colA1}${rowNumber}`,
    valueInputOption: "USER_ENTERED",
    requestBody: {
      values: [["済み"]],
    },
  });
}

export async function updateStaffNotes(
  sheetName: ReservationSheetName,
  rowNumber: number,
  notes: string
): Promise<void> {
  await ensureStatusColumns(sheetName);
  const headers = await getHeaderRow(sheetName);
  const notesIdx = headers.indexOf("スタッフ備考");
  if (notesIdx === -1) {
    throw new Error("Notes column not found");
  }

  const sheets = getSheetsClient();
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;
  const colA1 = columnIndexToA1(notesIdx);

  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range: `${sheetName}!${colA1}${rowNumber}`,
    valueInputOption: "USER_ENTERED",
    requestBody: {
      values: [[notes]],
    },
  });
}
