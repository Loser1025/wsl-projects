const { google } = require('googleapis');
const {
  validateEnvVar,
  setCorsHeaders,
  handleOptions,
  handleError,
  handleGoogleCalendarError,
  initFirebaseAdmin,
  getFirestore,
  createApiHandler,
} = require('./_utils');

const { FieldValue } = require('firebase-admin/firestore');

async function createBookingHandler(req, res) {
  // Validate environment variables
  const serviceAccount = validateEnvVar('FIREBASE_SERVICE_ACCOUNT_KEY', res);
  if (!serviceAccount) {
    return; // Response already sent
  }

  const booking = req.body;

  // Validate required booking fields
  if (!booking || !booking.calendarId || !booking.start || !booking.end) {
    return res.status(400).json({ error: 'Missing required booking fields: calendarId, start, end' });
  }

  let docRef = null;
  let db = null;

  try {
    // Initialize Firebase Admin with robust guard
    const app = initFirebaseAdmin(serviceAccount);

    db = getFirestore(app);

    // Use a transaction to prevent double-booking of the same time slot
    docRef = await db.runTransaction(async (transaction) => {
      // Check for existing booking with the same calendarId, start, and end
      const existingBookingsQuery = db
        .collection('bookings')
        .where('calendarId', '==', booking.calendarId)
        .where('start', '==', booking.start)
        .where('end', '==', booking.end)
        .limit(1);

      const existingBookingsSnapshot = await transaction.get(existingBookingsQuery);

      if (!existingBookingsSnapshot.empty) {
        // Double-booking detected: same calendarId, start, and end already exists
        const error = new Error('Time slot already booked');
        error.code = 'ALREADY_BOOKED';
        error.statusCode = 409;
        throw error;
      }

      // No existing booking - create new one within the transaction
      const newDocRef = db.collection('bookings').doc();
      transaction.set(newDocRef, {
        ...booking,
        createdAt: FieldValue.serverTimestamp(),
      });

      return newDocRef;
    });

    // Firestore booking created successfully - now create Google Calendar event
    const credentials = validateEnvVar('GOOGLE_SERVICE_ACCOUNT_KEY', res);
    if (!credentials) {
      return; // Response already sent
    }

    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ['https://www.googleapis.com/auth/calendar'],
    });

    const calendar = google.calendar({ version: 'v3', auth });

    const calendarResponse = await calendar.events.insert({
      calendarId: booking.calendarId,
      requestBody: {
        summary: '予約',
        start: { dateTime: booking.start, timeZone: 'Asia/Tokyo' },
        end: { dateTime: booking.end, timeZone: 'Asia/Tokyo' },
      },
    });

    const googleEventId = calendarResponse.data.id;

    res.status(200).json({ id: docRef.id, googleEventId });
  } catch (error) {
    if (error.code === 'ALREADY_BOOKED' || error.statusCode === 409) {
      return res.status(409).json({ error: 'Time slot already booked' });
    }

    // If Google Calendar API failed after Firestore booking was created,
    // we need to delete the Firestore booking to maintain consistency
    if (docRef && docRef.id && db) {
      try {
        await db.collection('bookings').doc(docRef.id).delete();
        console.log('Rolled back Firestore booking due to Calendar API failure:', docRef.id);
      } catch (deleteError) {
        console.error('Failed to rollback Firestore booking:', deleteError);
      }
    }

    const userMessage = handleGoogleCalendarError ? handleGoogleCalendarError(error) : '内部サーバーエラーが発生しました';
    handleError(error, res, userMessage);
  }
}

module.exports = createApiHandler(createBookingHandler);