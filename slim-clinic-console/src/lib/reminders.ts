import {
  listAllReservationsGrouped,
  getCustomerName,
  getCustomerEmail,
  getConfirmedDateTime,
  getMeetLink,
  getReminderSentFlag,
  parseConfirmedDateTime,
  markReminderSent,
  getJpLineFriendId,
  QUESTIONNAIRE_URL_MAP,
} from "@/lib/sheets";
import { sendReminderEmail } from "@/lib/google-actions";
import { sendLineReminderPush } from "@/lib/liny";

const REMINDER_LEAD_MS = 10 * 60 * 1000;

export type ReminderResult = {
  processed: number;
  sent: number;
  errors: string[];
};

export async function processReminders(): Promise<ReminderResult> {
  const { confirmed } = await listAllReservationsGrouped();
  const now = Date.now();
  const errors: string[] = [];
  let sent = 0;

  for (const record of confirmed) {
    if (getReminderSentFlag(record)) continue;

    const confirmedDateTime = getConfirmedDateTime(record);
    const target = parseConfirmedDateTime(confirmedDateTime);
    if (!target) continue;

    const reminderAt = target.getTime() - REMINDER_LEAD_MS;
    if (now < reminderAt || now >= target.getTime()) continue;

    const label = `${record.sheetName}#${record.rowNumber}`;

    try {
      const email = getCustomerEmail(record);
      const meetLink = getMeetLink(record);
      if (email) {
        await sendReminderEmail({
          to: email,
          customerName: getCustomerName(record),
          confirmedDateTime,
          questionnaireUrl: QUESTIONNAIRE_URL_MAP[record.sheetName],
          meetLink: meetLink || undefined,
        });
      }

      if (record.sheetName === "国内") {
        try {
          const friendId = await getJpLineFriendId(record.rowNumber);
          if (friendId) {
            await sendLineReminderPush(friendId, {
              confirmed_datetime: confirmedDateTime,
              meet_link: meetLink || "対面でのご来院となりますため、本リンクはございません。",
              questionnaire_url: QUESTIONNAIRE_URL_MAP[record.sheetName],
            });
          }
        } catch (linePushErr) {
          errors.push(`${label} line_push_failed: ${String(linePushErr)}`);
        }
      }

      await markReminderSent(record.sheetName, record.rowNumber);
      sent++;
    } catch (err) {
      errors.push(`${label} reminder_failed: ${String(err)}`);
    }
  }

  return { processed: confirmed.length, sent, errors };
}
