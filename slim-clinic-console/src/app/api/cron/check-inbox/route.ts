import { NextRequest, NextResponse } from "next/server";
import { processInboxNotifications } from "@/lib/inbox-notify";

export async function GET(req: NextRequest) {
  const expected = process.env.CRON_SECRET;
  const authHeader = req.headers.get("authorization");

  if (!expected || authHeader !== `Bearer ${expected}`) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  try {
    const result = await processInboxNotifications();
    return NextResponse.json(result);
  } catch (err) {
    console.error("process_inbox_notifications_failed", err);
    return NextResponse.json({ error: "process_inbox_notifications_failed" }, { status: 500 });
  }
}
