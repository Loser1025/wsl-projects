# AGENTS.md

Guidance for any AI coding agent (Claude Code, Codex, Cursor, etc.) working in this repo.

## What this project is

`mission-control-v2` — a single-page internal dashboard ("事業部タスク管理" / "顧客管理" / "ドライブ") for
tracking division tasks, a customer CRM list, and browsing an assigned Google Drive folder.
Deployed on Vercel (project `mission-control-v2`).

## Architecture

- **Everything UI lives in one file: `index.html`.** There is no build step for the frontend —
  it's a template (`<x-dc>...</x-dc>`) plus a single `<script type="text/x-dc" data-dc-script>`
  containing one `class Component extends DCLogic { ... }`.
- **Templating**: a small custom runtime (`support.js`, generated — see header comment, do not
  hand-edit) provides `sc-if` / `sc-for` directives and `{{ expr }}` interpolation, React-backed.
  `Component.render()` (near the bottom of the script block) returns a big object of computed
  values/handlers that the template binds to.
- **State**: one flat `state = { ... }` object on `Component`. Updates go through
  `this.setState({...})`. There is no Redux/store — just this class.
- **Persistence**: `localStorage` is the source of truth on load (`loadTasks()`,
  `loadSections()`, `loadCustomers()`), and every mutation calls `persist(...)` /
  `persistCustomers(...)` which also mirrors to Firebase Realtime Database
  (`window._db.ref('tasks').set(tasks)`, etc.) for cross-device sync. Firebase config is inlined
  near the top of `index.html`.
- **Task / customer modals**: the codebase deliberately reuses one modal for add+edit
  (see `openTaskAdd` / `openTaskEdit` / `saveTask` for tasks, `openCustAdd` / `openCustEdit` /
  `saveCustomer` for customers). Follow this pattern rather than introducing a second modal
  when adding "edit" support for something new.
- **Backend**: `api/*.js` are Vercel serverless functions (Node, `module.exports = async (req,res) => ...`,
  no framework). They proxy Google Drive API calls (`googleapis`) using the signed-in user's
  OAuth access token forwarded from the browser as `Authorization: Bearer <token>` — see
  `api/_drive.js`. There is no service-account fallback in the current auth model; every Drive
  call runs as the logged-in Google user, scoped to `DRIVE_ROOT_FOLDER_ID` via `isUnderRoot()`.
  A Drive 403 usually means the signed-in Google account itself lacks access to that folder, not
  a bug in the app.
- **Auth**: Google Identity Services token client (`google.accounts.oauth2`), client ID served
  from `/api/config` (`GOOGLE_CLIENT_ID` env var). Token kept in `sessionStorage` only
  (`fulcrum_auth`), never persisted longer-term.

## Environment variables (Vercel project settings, not in repo)

- `GOOGLE_CLIENT_ID` — OAuth client ID for Drive sign-in.
- `DRIVE_ROOT_FOLDER_ID` — Drive folder all API calls are scoped under.
- `FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY` — Firebase Admin creds
  (server-side use; check `api/` before assuming these are wired into a given endpoint).
- `SERVICE_ACCOUNT_JSON` — legacy, predates the per-user OAuth Drive switch; verify it's still
  referenced anywhere before relying on it.

## Making changes

- Edit `index.html` directly for UI/state/behavior. Do not edit `support.js` (regenerated from a
  separate `dc-runtime` TS source not present in this repo checkout — see file header).
- After editing, sanity-check the inline script parses before deploying:
  ```bash
  node -e "
  const fs=require('fs');
  const html=fs.readFileSync('index.html','utf8');
  const scripts=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
  scripts.forEach(s=>{ if(s.trim()) new Function(s); });
  console.log('OK');
  "
  ```
- No automated test suite (`npm test` is a stub). No linter configured. Verification is manual —
  read the diff carefully, check every `{{ handler }}` referenced in the template has a matching
  key in the `render()` return object, and (when possible) exercise the flow in a browser.

## Deploy

- Vercel CLI, project already linked (`.vercel/project.json`).
- Preview: `vercel`
- Production: `vercel --prod` — **treat as a real production push affecting live users; confirm
  with the user before running it**, and prefer committing changes to git first so history stays
  accurate (Vercel CLI deploys whatever is in the working directory, committed or not).

## Conventions observed in this codebase

- Japanese UI copy and comments throughout; keep new UI text in Japanese to match.
- Inline styles via JS style objects (no CSS framework, minimal `<style>` block at the top for a
  few utility classes like `.mc-task-wrap`).
- Flat, un-abstracted handler functions on `Component` (`updateField`, `deleteTask`,
  `openTaskEdit`, ...) — mirror this style rather than introducing new abstractions/helpers
  unless the task clearly calls for it.
