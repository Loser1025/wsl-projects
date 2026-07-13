const { getDriveClient, getRootFolderId, isUnderRoot } = require('./_drive');

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method Not Allowed' });

  try {
    const { fileId } = req.body || {};
    if (!fileId) return res.status(400).json({ error: 'Missing fileId' });
    if (fileId === getRootFolderId()) return res.status(403).json({ error: 'Cannot delete root folder' });

    const allowed = await isUnderRoot(fileId);
    if (!allowed) return res.status(403).json({ error: 'Invalid file' });

    const drive = getDriveClient();
    // Move to trash instead of a hard delete so accidental removals are recoverable.
    await drive.files.update({
      fileId,
      requestBody: { trashed: true },
      supportsAllDrives: true,
    });

    res.status(200).json({ ok: true });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Drive API error: ' + error.message });
  }
};
