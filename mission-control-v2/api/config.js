module.exports = function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method Not Allowed' });
  res.status(200).json({ googleClientId: process.env.GOOGLE_CLIENT_ID || null });
};
