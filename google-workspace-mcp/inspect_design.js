import { google } from 'googleapis';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function main() {
    const credentialsPath = path.join(__dirname, 'credentials.json');
    const auth = new google.auth.GoogleAuth({
        keyFile: credentialsPath,
        scopes: ['https://www.googleapis.com/auth/spreadsheets'],
    });
    const sheets = google.sheets({ version: 'v4', auth });
    const spreadsheetId = '1aFB2O37w-Dh0RmN_W2CultjS1X4Vb7LqxbKMb99UVp4';

    const res = await sheets.spreadsheets.get({ spreadsheetId });
    console.log("Sheets in spreadsheet:");
    res.data.sheets?.forEach(s => {
        console.log(`- ${s.properties?.title} (ID: ${s.properties?.sheetId})`);
    });
}

main().catch(console.error);
