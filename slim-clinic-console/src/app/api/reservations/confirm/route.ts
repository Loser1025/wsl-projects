import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { confirmReservation, ReservationSheetName, RESERVATION_SHEET_NAMES, getJpLineFriendId } from "@/lib/sheets";
import { createMeetSpace, sendConfirmationEmail } from "@/lib/google-actions";
import { sendLinePush } from "@/lib/liny";

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const body = await req.json();
  const { sheetName, rowNumber, confirmedDateTime, customerName, customerEmail, questionnaireUrl, isOnline } = body;

  if (
    !sheetName ||
    !RESERVATION_SHEET_NAMES.includes(sheetName) ||
    !rowNumber ||
    !confirmedDateTime ||
    !customerEmail
  ) {
    return NextResponse.json({ error: "missing_field" }, { status: 400 });
  }

  try {
    const meetLink = isOnline ? await createMeetSpace() : "";
    await sendConfirmationEmail({
      to: customerEmail,
      customerName: customerName || "",
      confirmedDateTime,
      questionnaireUrl: questionnaireUrl || "",
      meetLink: meetLink || undefined,
      sheetName: sheetName as ReservationSheetName,
    });
    await confirmReservation(sheetName as ReservationSheetName, rowNumber, confirmedDateTime, meetLink);

    let linePushed = false;
    if (sheetName === "国内") {
      try {
        const friendId = await getJpLineFriendId(rowNumber);
        if (friendId) {
          await sendLinePush(friendId, {
            confirmed_datetime: confirmedDateTime,
            meet_link: meetLink || "対面でのご来院となりますため、本リンクはございません。",
            questionnaire_url: questionnaireUrl || "",
          });
          linePushed = true;
        }
      } catch (linePushErr) {
        console.error("line_push_failed", linePushErr);
      }
    }

    return NextResponse.json({ ok: true, meetLink, linePushed });
  } catch (err) {
    console.error("confirm_failed", err);
    return NextResponse.json({ error: "confirm_failed" }, { status: 500 });
  }
}
