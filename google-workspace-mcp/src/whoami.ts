import { google } from "googleapis";
import { getAuthorizedClient } from "./auth.js";

const auth = await getAuthorizedClient();
const drive = google.drive({ version: "v3", auth });
const about = await drive.about.get({ fields: "user" });
console.log("Authorized as:", about.data.user?.emailAddress);
