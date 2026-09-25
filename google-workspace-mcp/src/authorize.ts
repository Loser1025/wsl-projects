import fs from "node:fs";
import http from "node:http";
import { newOAuth2Client, SCOPES, TOKEN_PATH } from "./auth.js";

async function main() {
  const client = newOAuth2Client();

  const server = http.createServer();
  await new Promise<void>((resolve) => server.listen(0, "localhost", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("failed to start local server");
  const redirectUri = `http://localhost:${address.port}`;

  const authUrl = client.generateAuthUrl({
    access_type: "offline",
    prompt: "consent",
    scope: SCOPES,
    redirect_uri: redirectUri,
  });

  console.log("Open this URL in a browser and approve access:\n");
  console.log(authUrl);
  console.log("\nWaiting for you to complete the consent screen...");

  const code = await new Promise<string>((resolve, reject) => {
    server.on("request", (req, res) => {
      const url = new URL(req.url ?? "", redirectUri);
      const code = url.searchParams.get("code");
      const error = url.searchParams.get("error");
      res.end(error ? `Authorization failed: ${error}. You can close this tab.` : "Authorization complete. You can close this tab.");
      if (error) reject(new Error(error));
      else if (code) resolve(code);
    });
  });

  server.close();

  const { tokens } = await client.getToken({ code, redirect_uri: redirectUri });
  fs.writeFileSync(TOKEN_PATH, JSON.stringify(tokens, null, 2));
  console.log(`\nSaved refresh token to ${TOKEN_PATH}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
