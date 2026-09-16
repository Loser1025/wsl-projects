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

    // Get spreadsheet to find sheetId of 月別金額集計_300万
    const res = await sheets.spreadsheets.get({ spreadsheetId });
    const targetSheet = res.data.sheets?.find(s => s.properties?.title === '月別金額集計_300万');
    if (!targetSheet || !targetSheet.properties?.sheetId) {
        throw new Error("Sheet '月別金額集計_300万' not found");
    }
    const sheetId = targetSheet.properties.sheetId;
    console.log(`Target sheetId: ${sheetId}`);

    // Let's inspect rows of 月別金額集計_300万 to see its length
    const resGrid = await sheets.spreadsheets.get({
        spreadsheetId,
        includeGridData: true
    });
    const sheetData = resGrid.data.sheets?.find(s => s.properties?.title === '月別金額集計_300万');
    const rowCount = sheetData?.data?.[0]?.rowData?.length || 12;
    console.log(`Row count in 月別金額集計_300万: ${rowCount}`);

    // Define styles
    // Header background: rgb(0.2, 0.298, 0.498) -> #334D7F
    // Row header background (col 0, rows 1..rowCount-2): rgb(0.949, 0.949, 0.949) -> #F2F2F2
    // Total row background (last row): rgb(0.898, 0.898, 0.898) -> #E5E5E5

    const requests = [
        // 1. Header Row (Row 0): background #334D7F, text white, bold, center aligned
        {
            repeatCell: {
                range: {
                    sheetId,
                    startRowIndex: 0,
                    endRowIndex: 1,
                    startColumnIndex: 0,
                    endColumnIndex: 11
                },
                cell: {
                    userEnteredFormat: {
                        backgroundColor: { red: 0.2, green: 0.298, blue: 0.498 },
                        textFormat: {
                            foregroundColor: { red: 1, green: 1, blue: 1 },
                            bold: true
                        },
                        horizontalAlignment: 'CENTER'
                    }
                },
                fields: 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
            }
        },
        // 2. Row headers / Row labels (Col 0, Rows 1 to rowCount-2): background #F2F2F2, bold, left aligned
        {
            repeatCell: {
                range: {
                    sheetId,
                    startRowIndex: 1,
                    endRowIndex: rowCount - 1,
                    startColumnIndex: 0,
                    endColumnIndex: 1
                },
                cell: {
                    userEnteredFormat: {
                        backgroundColor: { red: 0.949, green: 0.949, blue: 0.949 },
                        textFormat: {
                            foregroundColor: { red: 0, green: 0, blue: 0 },
                            bold: true
                        },
                        horizontalAlignment: 'LEFT'
                    }
                },
                fields: 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
            }
        },
        // 3. Data cells (Col 1 to 10, Rows 1 to rowCount-2): background white, right aligned
        {
            repeatCell: {
                range: {
                    sheetId,
                    startRowIndex: 1,
                    endRowIndex: rowCount - 1,
                    startColumnIndex: 1,
                    endColumnIndex: 11
                },
                cell: {
                    userEnteredFormat: {
                        backgroundColor: { red: 1, green: 1, blue: 1 },
                        textFormat: {
                            foregroundColor: { red: 0, green: 0, blue: 0 },
                            bold: false
                        },
                        horizontalAlignment: 'RIGHT'
                    }
                },
                fields: 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
            }
        },
        // 4. Total row (Last row, Rows rowCount-1 to rowCount): background #E5E5E5, bold, col 0 left, col 1..10 right
        {
            repeatCell: {
                range: {
                    sheetId,
                    startRowIndex: rowCount - 1,
                    endRowIndex: rowCount,
                    startColumnIndex: 0,
                    endColumnIndex: 1
                },
                cell: {
                    userEnteredFormat: {
                        backgroundColor: { red: 0.898, green: 0.898, blue: 0.898 },
                        textFormat: {
                            foregroundColor: { red: 0, green: 0, blue: 0 },
                            bold: true
                        },
                        horizontalAlignment: 'LEFT'
                    }
                },
                fields: 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
            }
        },
        {
            repeatCell: {
                range: {
                    sheetId,
                    startRowIndex: rowCount - 1,
                    endRowIndex: rowCount,
                    startColumnIndex: 1,
                    endColumnIndex: 11
                },
                cell: {
                    userEnteredFormat: {
                        backgroundColor: { red: 0.898, green: 0.898, blue: 0.898 },
                        textFormat: {
                            foregroundColor: { red: 0, green: 0, blue: 0 },
                            bold: true
                        },
                        horizontalAlignment: 'RIGHT'
                    }
                },
                fields: 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
            }
        }
    ];

    const batchResponse = await sheets.spreadsheets.batchUpdate({
        spreadsheetId,
        requestBody: {
            requests
        }
    });

    console.log("Successfully applied formatting to '月別金額集計_300万'!", batchResponse.data);
}

main().catch(console.error);
