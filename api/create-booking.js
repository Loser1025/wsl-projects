const admin = require('firebase-admin');
const {
  validateEnvVar,
  setCorsHeaders,
  handleOptions,
  handleError,
  initFirebaseAdmin,
  createApiHandler,
} = require('./_utils');

async function createBookingHandler(req, res) {
  // Validate environment variable
  const serviceAccount = validateEnvVar('FIREBASE_SERVICE_ACCOUNT_KEY', res);
  if (!serviceAccount) {
    return; // Response already sent
  }

  const booking = req.body;

  // Validate required booking fields
  if (!booking || !booking.calendarId || !booking.start || !booking.end) {
    return res.status(400).json({ error: 'Missing required booking fields: calendarId, start, end' });
  }

  try {
    // Initialize Firebase Admin with robust guard
    initFirebaseAdmin(serviceAccount);

    const db = admin.firestore();

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
        createdAt: admin.firestore.FieldValue.serverTimestamp(),
      });

      return newDocRef;
    });

    res.status(200).json({ id: docRef.id });
  } catch (error) {
    if (error.code === 'ALREADY_BOOKED' || error.statusCode === 409) {
      return res.status(409).json({ error: 'Time slot already booked' });
    }
    handleError(error, res, '内部サーバーエラーが発生しました');
  }
}

module.exports = createApiHandler(createBookingHandler);
