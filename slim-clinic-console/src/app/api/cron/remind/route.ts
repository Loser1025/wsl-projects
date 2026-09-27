import { NextRequest, NextResponse } from "next/server";
import { processReminders } from "@/lib/reminders";

export async function GET(req: NextRequest) {
  const expected = process.env.CRON_SECRET;
  const authHeader = req.headers.get("authorization");

  if (!expected || authHeader !== `Bearer ${expected}`) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  try {
    const result = await processReminders();
    return NextResponse.json(result);
  } catch (err) {
    console.error("process_reminders_failed", err);
    return NextResponse.json({ error: "process_reminders_failed" }, { status: 500 });
  }
}
