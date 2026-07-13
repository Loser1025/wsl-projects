const { getAccessToken, getRootFolderId, isUnderRoot } = require('./_drive');

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method Not Allowed' });

  try {
    const { folderId, name, mimeType, size } = req.body || {};
    if (!name || !size) return res.status(400).json({ error: 'Missing name or size' });

    const targetFolderId = folderId || getRootFolderId();
    const allowed = await isUnderRoot(targetFolderId);
    if (!allowed) return res.status(403).json({ error: 'Invalid folder' });

    const token = await getAccessToken();

    const initRes = await fetch(
      'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true',
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json; charset=UTF-8',
          'X-Upload-Content-Type': mimeType || 'application/octet-stream',
          'X-Upload-Content-Length': String(size),
        },
        body: JSON.stringify({ name, parents: [targetFolderId] }),
      }
    );

    if (!initRes.ok) {
      const text = await initRes.text();
      return res.status(502).json({ error: `Drive session init failed: ${initRes.status} ${text}` });
    }

    const uploadUrl = initRes.headers.get('location');
    if (!uploadUrl) return res.status(502).json({ error: 'Drive did not return an upload URL' });

    res.status(200).json({ uploadUrl });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Drive API error: ' + error.message });
  }
};
