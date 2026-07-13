const { getDriveClient, requireBearerToken, isUnderRoot } = require('./_drive');

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method Not Allowed' });

  try {
    const token = requireBearerToken(req);
    const { fileId, newParentId } = req.body || {};
    if (!fileId || !newParentId) return res.status(400).json({ error: 'Missing fileId or newParentId' });

    const [fileAllowed, targetAllowed] = await Promise.all([
      isUnderRoot(fileId, token),
      isUnderRoot(newParentId, token),
    ]);
    if (!fileAllowed || !targetAllowed) return res.status(403).json({ error: 'Invalid file or target folder' });

    const drive = getDriveClient(token);
    const current = await drive.files.get({ fileId, fields: 'parents', supportsAllDrives: true });
    const previousParents = (current.data.parents || []).join(',');

    const result = await drive.files.update({
      fileId,
      addParents: newParentId,
      removeParents: previousParents,
      fields: 'id, name, mimeType, modifiedTime, webViewLink, iconLink, parents',
      supportsAllDrives: true,
    });

    res.status(200).json({ file: result.data });
  } catch (error) {
    console.error(error);
    res.status(error.statusCode || 500).json({ error: error.statusCode === 401 ? 'Not authenticated' : ('Drive API error: ' + error.message) });
  }
};
