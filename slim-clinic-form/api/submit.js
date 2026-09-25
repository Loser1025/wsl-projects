import { google } from "googleapis";

const REQUIRED_FIELDS = ["name", "email", "format", "date", "time"];

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).json({ error: "method_not_allowed" });
    return;
  }

  const body = req.body ?? {};
  for (const field of REQUIRED_FIELDS) {
    if (!body[field]) {
      res.status(400).json({ error: `missing_field:${field}` });
      return;
    }
  }
  const menu = Array.isArray(body.menu) ? body.menu : [];

  try {
    const auth = new google.auth.JWT({
      email: process.env.GOOGLE_SERVICE_ACCOUNT_EMAIL,
      key: process.env.GOOGLE_SERVICE_ACCOUNT_KEY.replace(/\\n/g, "\n"),
      scopes: ["https://www.googleapis.com/auth/spreadsheets"],
    });
    const sheets = google.sheets({ version: "v4", auth });

    await sheets.spreadsheets.values.append({
      spreadsheetId: process.env.GOOGLE_SHEET_ID,
      range: "'韓国'!A:K",
      valueInputOption: "USER_ENTERED",
      requestBody: {
        values: [[
          new Date().toISOString(),
          body.name,
          body.email,
          body.format,
          menu.join(", "),
          body.date,
          body.time,
          body.date2 || "",
          body.time2 || "",
          body.date3 || "",
          body.time3 || "",
        ]],
      },
    });

    res.status(200).json({ ok: true });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "sheet_write_failed" });
  }
}
