const { google } = require('googleapis');

function getRootFolderId() {
  const id = process.env.DRIVE_ROOT_FOLDER_ID;
  if (!id) throw new Error('Missing DRIVE_ROOT_FOLDER_ID env var');
  return id;
}

// Extracts the signed-in user's Google access token forwarded by the client
// as `Authorization: Bearer <token>`. All Drive calls run as this user, so
// they only ever see/touch what their own Google account has access to.
function getBearerToken(req) {
  const header = req.headers['authorization'] || req.headers['Authorization'];
  if (!header || !header.startsWith('Bearer ')) return null;
  return header.slice(7).trim() || null;
}

function requireBearerToken(req) {
  const token = getBearerToken(req);
  if (!token) {
    const err = new Error('Not authenticated');
    err.statusCode = 401;
    throw err;
  }
  return token;
}

function getDriveClient(token) {
  const auth = new google.auth.OAuth2();
  auth.setCredentials({ access_token: token });
  return google.drive({ version: 'v3', auth });
}

// Walks the parents chain from fileId up to the root folder, confirming
// the file lives inside DRIVE_ROOT_FOLDER_ID. Prevents the signed-in user
// from using this app to touch anything outside the shared folder.
async function isUnderRoot(fileId, token) {
  const rootId = getRootFolderId();
  if (fileId === rootId) return true;

  const drive = getDriveClient(token);
  let currentId = fileId;
  const seen = new Set();

  for (let depth = 0; depth < 50; depth++) {
    if (seen.has(currentId)) return false;
    seen.add(currentId);

    let file;
    try {
      file = await drive.files.get({
        fileId: currentId,
        fields: 'id, parents',
        supportsAllDrives: true,
      });
    } catch (e) {
      return false;
    }

    const parents = file.data.parents || [];
    if (parents.includes(rootId)) return true;
    if (parents.length === 0) return false;
    currentId = parents[0];
  }
  return false;
}

module.exports = { getDriveClient, getBearerToken, requireBearerToken, getRootFolderId, isUnderRoot };
