import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { cancelReservation, ReservationSheetName, RESERVATION_SHEET_NAMES } from "@/lib/sheets";
import { cancelNotificationEmail } from "@/lib/google-actions";

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const body = await req.json();
  const { sheetName, rowNumber, customerName, customerEmail } = body;

  if (!sheetName || !RESERVATION_SHEET_NAMES.includes(sheetName) || !rowNumber) {
    return NextResponse.json({ error: "missing_field" }, { status: 400 });
  }

  try {
    await cancelReservation(sheetName as ReservationSheetName, rowNumber);
    if (customerEmail) {
      await cancelNotificationEmail(customerEmail, customerName || "", sheetName as ReservationSheetName);
    }
    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("cancel_failed", err);
    return NextResponse.json({ error: "cancel_failed" }, { status: 500 });
  }
}
