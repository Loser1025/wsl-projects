export type LinePushParams = {
  confirmed_datetime: string;
  meet_link: string;
  questionnaire_url: string;
};

async function postToLinyCustomApi(
  url: string,
  token: string,
  friendId: string,
  params: LinePushParams
): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      uid: friendId,
      params,
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`LINY push failed: ${res.status} ${text}`);
  }
}

export async function sendLinePush(friendId: string, params: LinePushParams): Promise<void> {
  const url = process.env.LINY_CUSTOM_API_URL;
  const token = process.env.LINY_CUSTOM_API_TOKEN;
  if (!url || !token) {
    throw new Error("LINY_CUSTOM_API_URL or LINY_CUSTOM_API_TOKEN is not set");
  }
  await postToLinyCustomApi(url, token, friendId, params);
}

// 確定時通知とは別のLINY「連携アクション」（リマインド用メッセージ）を叩くための専用トリガー。
export async function sendLineReminderPush(friendId: string, params: LinePushParams): Promise<void> {
  const url = process.env.LINY_REMINDER_API_URL;
  const token = process.env.LINY_REMINDER_API_TOKEN;
  if (!url || !token) {
    throw new Error("LINY_REMINDER_API_URL or LINY_REMINDER_API_TOKEN is not set");
  }
  await postToLinyCustomApi(url, token, friendId, params);
}

export function verifyLinyWebhookSecret(headerValue: string | null): boolean {
  const expected = process.env.LINY_WEBHOOK_SECRET;
  if (!expected || !headerValue) return false;
  return headerValue === expected;
}

type LinyFormAnswer = {
  title?: string;
  value?: unknown;
};

type LinyWebhookPayload = {
  event_type?: string;
  data?: {
    friend?: { id?: number; uid?: string };
    event?: { answers?: LinyFormAnswer[] };
  };
};

export function extractFormAnswerText(payload: LinyWebhookPayload, title: string): string {
  const answers = payload.data?.event?.answers || [];
  const match = answers.find((a) => a.title === title);
  if (!match || typeof match.value !== "string") return "";
  return match.value;
}

export function extractFriendId(payload: LinyWebhookPayload): string {
  const friend = payload.data?.friend;
  if (!friend) return "";
  if (friend.uid) return friend.uid;
  return friend.id !== undefined && friend.id !== null ? String(friend.id) : "";
}

export type { LinyWebhookPayload };
