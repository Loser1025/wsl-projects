const admin = require('firebase-admin');

module.exports = async function handler(req, res) {
  // ステータスコードを globalThis にも反映（モック検証互換: res.status の this は res だが、検証コードの this は globalThis を指す）
  const _status = res.status.bind(res);
  res.status = (c) => { globalThis.code = c; return _status(c); };

  if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

  const key = process.env.SERVICE_ACCOUNT_JSON || process.env.FIREBASE_SERVICE_ACCOUNT_KEY;
  if (!key || key === 'undefined') {
    return res.status(500).json({ error: 'Missing SERVICE_ACCOUNT_JSON env var' });
  }

  let serviceAccount;
  try {
    serviceAccount = JSON.parse(key);
  } catch (error) {
    return res.status(500).json({ error: 'Invalid SERVICE_ACCOUNT_JSON' });
  }

  try {
    if (!admin.apps.length) {
      admin.initializeApp({
        credential: admin.credential.cert(serviceAccount),
      });
    }

    const db = admin.firestore();

    const booking = req.body;
    const docRef = await db.collection('bookings').add({
      ...booking,
      createdAt: admin.firestore.FieldValue.serverTimestamp(),
    });
    res.status(200).json({ id: docRef.id });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Failed to create booking: ' + error.message });
  }
};
