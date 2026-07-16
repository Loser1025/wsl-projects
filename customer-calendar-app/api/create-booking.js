const {
  validateEnvVar,
  setCorsHeaders,
  handleOptions,
  handleError,
  initFirebaseAdmin,
  getFirestore,
  createApiHandler,
} = require('./_utils');

const { google } = require('googleapis');
const { FieldValue } = require('firebase-admin/firestore');

async function createBookingHandler(req, res) {
  // Validate Firebase environment variable
  const serviceAccount = validateEnvVar('FIREBASE_SERVICE_ACCOUNT_KEY', res);
  if (!serviceAccount) {
    return; // Response already sent
  }

  const booking = req.body;

  // Validate required booking fields
  if (!booking || !booking.calendarId || !booking.start || !booking.end) {
    return res.status(400).json({ error: 'Missing required booking fields: calendarId, start, end' });
  }

  // Idempotency key from header (optional but recommended)
  const idempotencyKey = req.headers['idempotency-key'] || req.headers['Idempotency-Key'];

  let createdDocRef = null;
  let googleEventId = null;

  try {
    // Initialize Firebase Admin with robust guard
    const app = initFirebaseAdmin(serviceAccount);
    const db = getFirestore(app);

    // If idempotency key provided, check for existing booking with that key
    if (idempotencyKey) {
      const idempotencyRef = db.collection('idempotency_keys').doc(idempotencyKey);
      const idempotencySnap = await idempotencyRef.get();
      
      if (idempotencySnap.exists) {
        // Return the existing booking ID
        const existingData = idempotencySnap.data();
        return res.status(200).json({ 
          id: existingData.bookingId,
          idempotent: true 
        });
      }
    }

    // Use a transaction to prevent double-booking of the same time slot
    const docRef = await db.runTransaction(async (transaction) => {
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

      // If idempotency key provided, also store it in the same transaction
      if (idempotencyKey) {
        const idempotencyRef = db.collection('idempotency_keys').doc(idempotencyKey);
        transaction.set(idempotencyRef, {
          bookingId: newDocRef.id,
          createdAt: FieldValue.serverTimestamp(),
        });
      }

      return newDocRef;
    });

    createdDocRef = docRef;

    // Now create the event in Google Calendar
    const googleCredentials = validateEnvVar('GOOGLE_SERVICE_ACCOUNT_KEY', res);
    if (googleCredentials) {
      const auth = new google.auth.GoogleAuth({
        credentials: googleCredentials,
        scopes: ['https://www.googleapis.com/auth/calendar.events'],
      });

      const calendar = google.calendar({ version: 'v3', auth });

      const event = {
        summary: '予約',
        start: { dateTime: booking.start, timeZone: 'Asia/Tokyo' },
        end: { dateTime: booking.end, timeZone: 'Asia/Tokyo' },
      };

      const response = await calendar.events.insert({
        calendarId: booking.calendarId,
        requestBody: event,
      });

      googleEventId = response.data.id;

      // Update the booking document with the Google Calendar event ID
      await db.collection('bookings').doc(docRef.id).update({
        googleEventId: googleEventId,
        googleCalendarSyncedAt: FieldValue.serverTimestamp(),
      });

      // If idempotency key provided, also update it with googleEventId
      if (idempotencyKey) {
        await db.collection('idempotency_keys').doc(idempotencyKey).update({
          googleEventId: googleEventId,
        });
      }
    }

    res.status(200).json({ 
      id: docRef.id, 
      idempotent: false,
      googleEventId: googleEventId 
    });
  } catch (error) {
    // If Google Calendar creation failed but Firestore booking was created, delete it
    if (createdDocRef && !googleEventId) {
      try {
        const app = initFirebaseAdmin(serviceAccount);
        const db = getFirestore(app);
        await db.collection('bookings').doc(createdDocRef.id).delete();
        
        if (idempotencyKey) {
          await db.collection('idempotency_keys').doc(idempotencyKey).delete();
        }
      } catch (cleanupError) {
        console.error('Cleanup failed:', cleanupError);
      }
    }

    if (error.code === 'ALREADY_BOOKED' || error.statusCode === 409) {
      return res.status(409).json({ error: 'Time slot already booked' });
    }
    handleError(error, res, '内部サーバーエラーが発生しました');
  }
}

module.exports = createApiHandler(createBookingHandler);
