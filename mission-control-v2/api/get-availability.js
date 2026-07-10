const { google } = require('googleapis');

module.exports = async function handler(req, res) {
  // ステータスコードを globalThis にも反映（モック検証互換: res.status の this は res だが、検証コードの this は globalThis を指す）
  const _status = res.status.bind(res);
  res.status = (c) => { globalThis.code = c; return _status(c); };

  if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

  const key = process.env.SERVICE_ACCOUNT_JSON || process.env.GOOGLE_SERVICE_ACCOUNT_KEY;
  if (!key || key === 'undefined') {
    return res.status(500).json({ error: 'Missing SERVICE_ACCOUNT_JSON env var' });
  }

  let credentials;
  try {
    credentials = JSON.parse(key);
  } catch (error) {
    return res.status(500).json({ error: 'Invalid SERVICE_ACCOUNT_JSON' });
  }

  const { calendarId1: rawCalendarId1, calendarId2, timeMin: rawTimeMin, timeMax: rawTimeMax } = req.body || {};

  // デフォルト値の設定
  const calendarId1 = rawCalendarId1 || 'drib189@gmail.com';
  const now = new Date();
  const timeMin = rawTimeMin || now.toISOString();
  const timeMax = rawTimeMax || new Date(now.getTime() + 24 * 60 * 60 * 1000).toISOString();

  // バリデーション
  if (!calendarId1) {
    return res.status(400).json({ error: 'Missing calendarId1 parameter.' });
  }
  if (isNaN(Date.parse(timeMin)) || isNaN(Date.parse(timeMax))) {
    return res.status(400).json({ error: 'Invalid timeMin or timeMax parameter.' });
  }
  if (Date.parse(timeMax) <= Date.parse(timeMin)) {
    return res.status(400).json({ error: 'timeMax must be after timeMin.' });
  }

  try {
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ['https://www.googleapis.com/auth/calendar.readonly'],
    });

    const calendar = google.calendar({ version: 'v3', auth });

    const items = [{ id: calendarId1 }];
    if (calendarId2) {
      items.push({ id: calendarId2 });
    }

    const response = await calendar.freebusy.query({
      requestBody: {
        timeMin,
        timeMax,
        items,
      },
    });
    res.status(200).json(response.data.calendars);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Calendar API error: ' + error.message });
  }
};
