import { initializeApp } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';

// 初期化（環境変数で設定）
const app = initializeApp();
const db = getFirestore(app);

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ message: 'Method Not Allowed' });
  }

  try {
    const { customerName, date, time } = req.body;

    // バリデーション（省略）
    
    const bookingRef = await db.collection('bookings').add({
      customerName,
      date,
      time,
      createdAt: new Date().toISOString(),
    });

    res.status(200).json({ success: true, id: bookingRef.id });
  } catch (error) {
    console.error(error);
    res.status(500).json({ success: false, message: 'Internal Server Error' });
  }
}
