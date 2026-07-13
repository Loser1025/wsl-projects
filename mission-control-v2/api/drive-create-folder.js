const { getDriveClient, requireBearerToken, getRootFolderId, isUnderRoot } = require('./_drive');

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method Not Allowed' });

  try {
    const token = requireBearerToken(req);
    const { folderId, name } = req.body || {};
    if (!name || !name.trim()) return res.status(400).json({ error: 'Missing name' });

    const targetFolderId = folderId || getRootFolderId();
    const allowed = await isUnderRoot(targetFolderId, token);
    if (!allowed) return res.status(403).json({ error: 'Invalid folder' });

    const drive = getDriveClient(token);
    const result = await drive.files.create({
      requestBody: {
        name: name.trim(),
        mimeType: 'application/vnd.google-apps.folder',
        parents: [targetFolderId],
      },
      fields: 'id, name, mimeType, modifiedTime, webViewLink, iconLink, parents',
      supportsAllDrives: true,
    });

    res.status(200).json({ file: result.data });
  } catch (error) {
    console.error(error);
    res.status(error.statusCode || 500).json({ error: error.statusCode === 401 ? 'Not authenticated' : ('Drive API error: ' + error.message) });
  }
};
