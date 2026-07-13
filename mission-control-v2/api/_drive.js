const { google } = require('googleapis');

const SCOPES = ['https://www.googleapis.com/auth/drive'];

function loadCredentials() {
  const raw = process.env.SERVICE_ACCOUNT_JSON;
  if (!raw) throw new Error('Missing SERVICE_ACCOUNT_JSON env var');
  return JSON.parse(raw);
}

function getRootFolderId() {
  const id = process.env.DRIVE_ROOT_FOLDER_ID;
  if (!id) throw new Error('Missing DRIVE_ROOT_FOLDER_ID env var');
  return id;
}

function getAuth() {
  const credentials = loadCredentials();
  return new google.auth.GoogleAuth({ credentials, scopes: SCOPES });
}

function getDriveClient() {
  return google.drive({ version: 'v3', auth: getAuth() });
}

async function getAccessToken() {
  const client = await getAuth().getClient();
  const { token } = await client.getAccessToken();
  return token;
}

// Walks the parents chain from fileId up to the root folder, confirming
// the file lives inside DRIVE_ROOT_FOLDER_ID. Prevents the service account
// (which may have access to other files) from being used to touch anything
// outside the shared folder.
async function isUnderRoot(fileId) {
  const rootId = getRootFolderId();
  if (fileId === rootId) return true;

  const drive = getDriveClient();
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

module.exports = { getDriveClient, getAccessToken, getRootFolderId, isUnderRoot };
