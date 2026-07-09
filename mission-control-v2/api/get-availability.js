import { google } from 'googleapis';

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

  const { calendarId1, calendarId2, timeMin, timeMax } = req.body;

  const auth = new google.auth.GoogleAuth({
    credentials: JSON.parse(process.env.GOOGLE_SERVICE_ACCOUNT_KEY),
    scopes: ['https://www.googleapis.com/auth/calendar.readonly'],
  });

  const calendar = google.calendar({ version: 'v3', auth });

  try {
    const response = await calendar.freebusy.query({
      requestBody: {
        timeMin,
        timeMax,
        items: [{ id: calendarId1 }, { id: calendarId2 }],
      },
    });
    res.status(200).json(response.data.calendars);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Failed to fetch availability' });
  }
}
