const { getDriveClient, requireBearerToken, getRootFolderId, isUnderRoot } = require('./_drive');

module.exports = async function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method Not Allowed' });

  try {
    const token = requireBearerToken(req);
    const rootId = getRootFolderId();
    const folderId = req.query.folderId || rootId;

    const allowed = await isUnderRoot(folderId, token);
    if (!allowed) return res.status(403).json({ error: 'Invalid folder' });

    const drive = getDriveClient(token);
    const result = await drive.files.list({
      q: `'${folderId}' in parents and trashed = false`,
      fields: 'files(id, name, mimeType, modifiedTime, size, webViewLink, iconLink, parents)',
      orderBy: 'folder,name_natural',
      pageSize: 200,
      supportsAllDrives: true,
      includeItemsFromAllDrives: true,
    });
    res.status(200).json({ files: result.data.files || [], folderId });
  } catch (error) {
    console.error(error);
    res.status(error.statusCode || 500).json({ error: error.statusCode === 401 ? 'Not authenticated' : ('Drive API error: ' + error.message) });
  }
};
