import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { applyHistoryMatch, ReservationSheetName, RESERVATION_SHEET_NAMES } from "@/lib/sheets";

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const body = await req.json();
  const { sheetName, rowNumber, lineFriendId, staffNotes } = body;

  if (!sheetName || !RESERVATION_SHEET_NAMES.includes(sheetName) || !rowNumber) {
    return NextResponse.json({ error: "missing_field" }, { status: 400 });
  }

  try {
    await applyHistoryMatch(
      sheetName as ReservationSheetName,
      rowNumber,
      lineFriendId || "",
      staffNotes || ""
    );
    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("apply_history_match_failed", err);
    return NextResponse.json({ error: "apply_history_match_failed" }, { status: 500 });
  }
}
