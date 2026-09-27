import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { rescheduleReservation, ReservationSheetName, RESERVATION_SHEET_NAMES, getJpLineFriendId } from "@/lib/sheets";
import { sendRescheduleEmail } from "@/lib/google-actions";
import { sendLineReschedulePush } from "@/lib/liny";

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const body = await req.json();
  const { sheetName, rowNumber, newDateTime, customerName, customerEmail, questionnaireUrl, meetLink } = body;

  if (
    !sheetName ||
    !RESERVATION_SHEET_NAMES.includes(sheetName) ||
    !rowNumber ||
    !newDateTime ||
    !customerEmail
  ) {
    return NextResponse.json({ error: "missing_field" }, { status: 400 });
  }

  try {
    await rescheduleReservation(sheetName as ReservationSheetName, rowNumber, newDateTime);
    await sendRescheduleEmail({
      to: customerEmail,
      customerName: customerName || "",
      newDateTime,
      questionnaireUrl: questionnaireUrl || "",
      meetLink: meetLink || undefined,
      sheetName: sheetName as ReservationSheetName,
    });

    let linePushed = false;
    if (sheetName === "国内") {
      try {
        const friendId = await getJpLineFriendId(rowNumber);
        if (friendId) {
          await sendLineReschedulePush(friendId, {
            confirmed_datetime: newDateTime,
            meet_link: meetLink || "対面でのご来院となりますため、本リンクはございません。",
            questionnaire_url: questionnaireUrl || "",
          });
          linePushed = true;
        }
      } catch (linePushErr) {
        console.error("line_push_failed", linePushErr);
      }
    }

    return NextResponse.json({ ok: true, linePushed });
  } catch (err) {
    console.error("reschedule_failed", err);
    return NextResponse.json({ error: "reschedule_failed" }, { status: 500 });
  }
}
