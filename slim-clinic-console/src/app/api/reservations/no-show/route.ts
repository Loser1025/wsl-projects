import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { markNoShow, ReservationSheetName, RESERVATION_SHEET_NAMES } from "@/lib/sheets";
import { sendNoShowEmail } from "@/lib/google-actions";

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const body = await req.json();
  const { sheetName, rowNumber, customerEmail, meetLink } = body;

  if (!sheetName || !RESERVATION_SHEET_NAMES.includes(sheetName) || !rowNumber) {
    return NextResponse.json({ error: "missing_field" }, { status: 400 });
  }

  try {
    await markNoShow(sheetName as ReservationSheetName, rowNumber);

    // オンライン診療(Meetリンクあり)の無断キャンセルのみ、日程再調整メールを自動送信する。
    // 対面の無断キャンセルは文面が異なるため、現時点では通知しない。
    if (meetLink && customerEmail) {
      try {
        await sendNoShowEmail({
          to: customerEmail,
          customerName: body.customerName || "",
          meetLink,
          sheetName: sheetName as ReservationSheetName,
        });
      } catch (emailErr) {
        console.error("no_show_email_failed", emailErr);
      }
    }

    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("no_show_failed", err);
    return NextResponse.json({ error: "no_show_failed" }, { status: 500 });
  }
}
