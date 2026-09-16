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

    const res = await sheets.spreadsheets.get({
        spreadsheetId,
        includeGridData: true
    });

    const spreadsheet = res.data;
    spreadsheet.sheets?.forEach(s => {
        const title = s.properties?.title;
        if (title === '月別金額集計') {
            console.log(`=== Sheet: ${title} (ID: ${s.properties?.sheetId}) ===`);
            const gridData = s.data?.[0];
            if (gridData && gridData.rowData) {
                gridData.rowData.forEach((row, rIdx) => {
                    const rowValues = row.values?.map((cell, cIdx) => {
                        const val = cell.formattedValue || cell.effectiveValue?.stringValue || cell.effectiveValue?.numberValue || '';
                        const fmt = cell.effectiveFormat;
                        const bg = fmt?.backgroundColor ? `rgb(${fmt.backgroundColor.red || 0},${fmt.backgroundColor.green || 0},${fmt.backgroundColor.blue || 0})` : 'default';
                        const fg = fmt?.textFormat?.foregroundColor ? `rgb(${fmt.textFormat.foregroundColor.red || 0},${fmt.textFormat.foregroundColor.green || 0},${fmt.textFormat.foregroundColor.blue || 0})` : 'default';
                        const ha = fmt?.horizontalAlignment || 'default';
                        return `[C${cIdx}: ${val} (bg:${bg}, fg:${fg}, bold:${fmt?.textFormat?.bold}, align:${ha})]`;
                    }).join(' | ');
                    console.log(`Row ${rIdx}: ${rowValues}`);
                });
            }
        }
    });
}

main().catch(console.error);
