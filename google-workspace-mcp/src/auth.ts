import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { OAuth2Client } from "google-auth-library";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

export const CREDENTIALS_PATH =
  process.env.GOOGLE_CREDENTIALS_PATH ?? path.join(ROOT, "credentials.json");

export const TOKEN_PATH = process.env.GOOGLE_TOKEN_PATH ?? path.join(ROOT, "token.json");

export const SCOPES = [
  "https://www.googleapis.com/auth/presentations",
  "https://www.googleapis.com/auth/spreadsheets",
  "https://www.googleapis.com/auth/documents",
  "https://www.googleapis.com/auth/drive",
  "https://www.googleapis.com/auth/forms.body",
  "https://www.googleapis.com/auth/forms.responses.readonly",
];

interface OAuthClientKey {
  client_id: string;
  client_secret: string;
  redirect_uris?: string[];
}

interface OAuthClientFile {
  installed?: OAuthClientKey;
  web?: OAuthClientKey;
}

export function loadOAuthClientKey(): OAuthClientKey {
  if (!fs.existsSync(CREDENTIALS_PATH)) {
    throw new Error(
      `credentials.json not found at ${CREDENTIALS_PATH}. Download an OAuth client (type: Desktop app) from Google Cloud Console > APIs & Services > Credentials and save it there.`,
    );
  }
  const raw: OAuthClientFile = JSON.parse(fs.readFileSync(CREDENTIALS_PATH, "utf-8"));
  const key = raw.installed ?? raw.web;
  if (!key) {
    throw new Error(
      `credentials.json at ${CREDENTIALS_PATH} is not an OAuth client secret file (expected "installed" or "web" key). Re-download it as an OAuth client ID of type "Desktop app".`,
    );
  }
  return key;
}

export function newOAuth2Client(): OAuth2Client {
  const key = loadOAuthClientKey();
  return new OAuth2Client(key.client_id, key.client_secret);
}

export async function getAuthorizedClient(): Promise<OAuth2Client> {
  if (!fs.existsSync(TOKEN_PATH)) {
    throw new Error(
      `${TOKEN_PATH} not found. Run "npm run authorize" once to grant access and store a refresh token.`,
    );
  }
  const client = newOAuth2Client();
  const token = JSON.parse(fs.readFileSync(TOKEN_PATH, "utf-8"));
  client.setCredentials(token);
  client.on("tokens", (fresh) => {
    const merged = { ...token, ...fresh };
    fs.writeFileSync(TOKEN_PATH, JSON.stringify(merged, null, 2));
  });
  return client;
}
