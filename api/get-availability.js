const { google } = require('googleapis');
const {
  validateEnvVar,
  setCorsHeaders,
  handleOptions,
  handleGoogleCalendarError,
  handleError,
  validateFreeBusyResponse,
  createApiHandler,
} = require('./_utils');

async function getAvailabilityHandler(req, res) {
  // Validate environment variable
  const credentials = validateEnvVar('GOOGLE_SERVICE_ACCOUNT_KEY', res);
  if (!credentials) {
    return; // Response already sent
  }

  const { calendarId1, calendarId2, timeMin, timeMax } = req.body || {};

  // Validate required fields
  if (!calendarId1 || !calendarId2 || !timeMin || !timeMax) {
    return res.status(400).json({ error: 'Missing required parameters: calendarId1, calendarId2, timeMin, timeMax' });
  }

  try {
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ['https://www.googleapis.com/auth/calendar.readonly'],
    });

    const calendar = google.calendar({ version: 'v3', auth });

    const response = await calendar.freebusy.query({
      requestBody: {
        timeMin,
        timeMax,
        items: [{ id: calendarId1 }, { id: calendarId2 }],
      },
    });

    // Defensive check on response structure
    if (!validateFreeBusyResponse(response.data.calendars)) {
      console.error('Invalid FreeBusy response structure:', response.data);
      return handleError(new Error('Invalid calendar response structure'), res, 'カレンダー情報の取得に失敗しました');
    }

    res.status(200).json(response.data.calendars);
  } catch (error) {
    const userMessage = handleGoogleCalendarError(error);
    handleError(error, res, userMessage);
  }
}

module.exports = createApiHandler(getAvailabilityHandler);