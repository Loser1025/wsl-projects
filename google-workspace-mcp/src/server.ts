import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { google } from "googleapis";
import { getAuthorizedClient } from "./auth.js";

const auth = await getAuthorizedClient();
const slides = google.slides({ version: "v1", auth });
const sheets = google.sheets({ version: "v4", auth });
const docs = google.docs({ version: "v1", auth });

const server = new McpServer({ name: "google-workspace-mcp", version: "1.0.0" });

function text(payload: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(payload, null, 2) }] };
}

// ---------- Slides ----------

server.registerTool(
  "slides_get",
  {
    description: "Get the full structure (slides, pages, elements, text) of a Google Slides presentation.",
    inputSchema: { presentationId: z.string() },
  },
  async ({ presentationId }) => {
    const res = await slides.presentations.get({ presentationId });
    return text(res.data);
  },
);

server.registerTool(
  "slides_batch_update",
  {
    description:
      "Apply a batchUpdate to a presentation using raw Google Slides API request objects (https://developers.google.com/slides/api/reference/rest/v1/presentations/batchUpdate). Use for anything not covered by slides_replace_text.",
    inputSchema: { presentationId: z.string(), requests: z.array(z.record(z.any())) },
  },
  async ({ presentationId, requests }) => {
    const res = await slides.presentations.batchUpdate({ presentationId, requestBody: { requests } });
    return text(res.data);
  },
);

server.registerTool(
  "slides_replace_text",
  {
    description: "Replace all occurrences of a text string across every slide in a presentation.",
    inputSchema: {
      presentationId: z.string(),
      findText: z.string(),
      replaceText: z.string(),
      matchCase: z.boolean().optional(),
    },
  },
  async ({ presentationId, findText, replaceText, matchCase }) => {
    const res = await slides.presentations.batchUpdate({
      presentationId,
      requestBody: {
        requests: [
          {
            replaceAllText: {
              containsText: { text: findText, matchCase: matchCase ?? false },
              replaceText,
            },
          },
        ],
      },
    });
    return text(res.data);
  },
);

// ---------- Sheets ----------

server.registerTool(
  "sheets_get_values",
  {
    description: "Read cell values from a spreadsheet range, e.g. 'Sheet1!A1:D10'.",
    inputSchema: { spreadsheetId: z.string(), range: z.string() },
  },
  async ({ spreadsheetId, range }) => {
    const res = await sheets.spreadsheets.values.get({ spreadsheetId, range });
    return text(res.data);
  },
);

server.registerTool(
  "sheets_update_values",
  {
    description: "Overwrite cell values in a spreadsheet range. values is a 2D array of rows.",
    inputSchema: {
      spreadsheetId: z.string(),
      range: z.string(),
      values: z.array(z.array(z.any())),
      valueInputOption: z.enum(["RAW", "USER_ENTERED"]).optional(),
    },
  },
  async ({ spreadsheetId, range, values, valueInputOption }) => {
    const res = await sheets.spreadsheets.values.update({
      spreadsheetId,
      range,
      valueInputOption: valueInputOption ?? "USER_ENTERED",
      requestBody: { values },
    });
    return text(res.data);
  },
);

server.registerTool(
  "sheets_append_values",
  {
    description: "Append rows after the last row of data in the given range/sheet.",
    inputSchema: {
      spreadsheetId: z.string(),
      range: z.string(),
      values: z.array(z.array(z.any())),
      valueInputOption: z.enum(["RAW", "USER_ENTERED"]).optional(),
    },
  },
  async ({ spreadsheetId, range, values, valueInputOption }) => {
    const res = await sheets.spreadsheets.values.append({
      spreadsheetId,
      range,
      valueInputOption: valueInputOption ?? "USER_ENTERED",
      requestBody: { values },
    });
    return text(res.data);
  },
);

server.registerTool(
  "sheets_batch_update",
  {
    description:
      "Apply structural/formatting changes using raw Google Sheets API request objects (https://developers.google.com/sheets/api/reference/rest/v4/spreadsheets/request). Use for formatting, adding sheets, merging cells, etc.",
    inputSchema: { spreadsheetId: z.string(), requests: z.array(z.record(z.any())) },
  },
  async ({ spreadsheetId, requests }) => {
    const res = await sheets.spreadsheets.batchUpdate({ spreadsheetId, requestBody: { requests } });
    return text(res.data);
  },
);

// ---------- Docs ----------

server.registerTool(
  "docs_get",
  {
    description: "Get the full structure and content of a Google Doc.",
    inputSchema: { documentId: z.string() },
  },
  async ({ documentId }) => {
    const res = await docs.documents.get({ documentId });
    return text(res.data);
  },
);

server.registerTool(
  "docs_batch_update",
  {
    description:
      "Apply a batchUpdate to a document using raw Google Docs API request objects (https://developers.google.com/docs/api/reference/rest/v1/documents/request). Use for inserting/deleting text, formatting, tables, etc.",
    inputSchema: { documentId: z.string(), requests: z.array(z.record(z.any())) },
  },
  async ({ documentId, requests }) => {
    const res = await docs.documents.batchUpdate({ documentId, requestBody: { requests } });
    return text(res.data);
  },
);

server.registerTool(
  "docs_replace_text",
  {
    description: "Replace all occurrences of a text string in a document.",
    inputSchema: {
      documentId: z.string(),
      findText: z.string(),
      replaceText: z.string(),
      matchCase: z.boolean().optional(),
    },
  },
  async ({ documentId, findText, replaceText, matchCase }) => {
    const res = await docs.documents.batchUpdate({
      documentId,
      requestBody: {
        requests: [
          {
            replaceAllText: {
              containsText: { text: findText, matchCase: matchCase ?? false },
              replaceText,
            },
          },
        ],
      },
    });
    return text(res.data);
  },
);

server.registerTool(
  "docs_insert_text",
  {
    description: "Insert text at a given index in a document (index 1 is the very start of the body).",
    inputSchema: { documentId: z.string(), text: z.string(), index: z.number().int().min(1) },
  },
  async ({ documentId, text: insertText, index }) => {
    const res = await docs.documents.batchUpdate({
      documentId,
      requestBody: { requests: [{ insertText: { text: insertText, location: { index } } }] },
    });
    return text(res.data);
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
