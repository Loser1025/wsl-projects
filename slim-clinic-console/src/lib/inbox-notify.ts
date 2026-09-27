import { listUnreadInboxMessages, markInboxMessageRead } from "@/lib/google-actions";
import { sendTelegramMessage } from "@/lib/telegram";

export type InboxNotifyResult = {
  processed: number;
  notified: number;
  errors: string[];
};

export async function processInboxNotifications(): Promise<InboxNotifyResult> {
  const messages = await listUnreadInboxMessages();
  const threadId = process.env.TELEGRAM_INBOX_THREAD_ID;
  const errors: string[] = [];
  let notified = 0;

  for (const message of messages) {
    try {
      const text =
        `📧 新着メール(online@slim-clinic.beauty)\n\n` +
        `・送信者: ${message.from}\n` +
        `・件名: ${message.subject}\n` +
        `・本文: ${message.snippet}`;
      await sendTelegramMessage(text, threadId);
      await markInboxMessageRead(message.id);
      notified++;
    } catch (err) {
      errors.push(`${message.id}: ${String(err)}`);
    }
  }

  return { processed: messages.length, notified, errors };
}
