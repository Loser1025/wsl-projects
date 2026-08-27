import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { google } from "googleapis";
import type { JWT } from "google-auth-library";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

export const CREDENTIALS_PATH =
  process.env.GOOGLE_CREDENTIALS_PATH ?? path.join(ROOT, "credentials.json");

export const SCOPES = [
  "https://www.googleapis.com/auth/presentations",
  "https://www.googleapis.com/auth/spreadsheets",
  "https://www.googleapis.com/auth/documents",
  "https://www.googleapis.com/auth/drive",
];

interface ServiceAccountKey {
  type: string;
  client_email: string;
  private_key: string;
}

export async function getAuthorizedClient(): Promise<JWT> {
  if (!fs.existsSync(CREDENTIALS_PATH)) {
    throw new Error(
      `credentials.json not found at ${CREDENTIALS_PATH}. Download a service account key from Google Cloud Console and save it there.`,
    );
  }
  const raw: ServiceAccountKey = JSON.parse(fs.readFileSync(CREDENTIALS_PATH, "utf-8"));
  if (raw.type !== "service_account") {
    throw new Error(`credentials.json at ${CREDENTIALS_PATH} is not a service account key (type=${raw.type})`);
  }
  const client = new google.auth.JWT({
    email: raw.client_email,
    key: raw.private_key,
    scopes: SCOPES,
  });
  await client.authorize();
  return client;
}

export function serviceAccountEmail(): string {
  const raw: ServiceAccountKey = JSON.parse(fs.readFileSync(CREDENTIALS_PATH, "utf-8"));
  return raw.client_email;
}
