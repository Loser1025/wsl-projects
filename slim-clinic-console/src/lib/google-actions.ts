import { google } from "googleapis";
import { OAuth2Client } from "google-auth-library";

function getOAuth2Client(): OAuth2Client {
  const clientId = process.env.GOOGLE_OAUTH_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_OAUTH_CLIENT_SECRET;
  const refreshToken = process.env.GOOGLE_OAUTH_REFRESH_TOKEN;

  const auth = new OAuth2Client({
    clientId,
    clientSecret,
  });

  if (refreshToken) {
    auth.setCredentials({ refresh_token: refreshToken });
  }

  return auth;
}

export async function createMeetSpace(): Promise<string> {
  const auth = getOAuth2Client();
  const meet = google.meet({ version: "v2", auth });
  const res = await meet.spaces.create({
    requestBody: {},
  });

  const meetingUri = res.data.meetingUri;
  if (!meetingUri) {
    throw new Error("Failed to create Google Meet space: meetingUri is missing");
  }

  return meetingUri;
}

async function sendPlainTextEmail(to: string, subject: string, body: string): Promise<void> {
  const auth = getOAuth2Client();
  const gmail = google.gmail({ version: "v1", auth });
  const senderEmail = process.env.GOOGLE_OAUTH_SENDER_EMAIL;

  if (!senderEmail) {
    throw new Error("GOOGLE_OAUTH_SENDER_EMAIL is not set");
  }

  const encodedSubject = `=?UTF-8?B?${Buffer.from(subject, "utf-8").toString("base64")}?=`;

  const rawMessage = [
    `From: ${senderEmail}`,
    `To: ${to}`,
    `Subject: ${encodedSubject}`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=UTF-8",
    "Content-Transfer-Encoding: base64",
    "",
    Buffer.from(body, "utf-8").toString("base64"),
  ].join("\r\n");

  const encodedMessage = Buffer.from(rawMessage)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

  await gmail.users.messages.send({
    userId: "me",
    requestBody: {
      raw: encodedMessage,
    },
  });
}

export type ConfirmationEmailInput = {
  to: string;
  customerName: string;
  confirmedDateTime: string;
  questionnaireUrl: string;
  meetLink: string;
};

export async function sendConfirmationEmail(
  input: ConfirmationEmailInput
): Promise<void> {
  const body = `${input.customerName} 様

このたびはご予約いただき誠にありがとうございます。
下記の内容でご予約が確定いたしました。

■ 確定日時
${input.confirmedDateTime}

■ 事前問診票（ご来院前にご記入ください）
${input.questionnaireUrl}

■ オンライン診療用リンク（Google Meet）
${input.meetLink}

ご不明な点がございましたらお気軽にお問い合わせください。`;

  await sendPlainTextEmail(input.to, "【ご予約確定のお知らせ】", body);
}

export async function cancelNotificationEmail(
  to: string,
  customerName: string
): Promise<void> {
  const body = `${customerName} 様

ご予約がキャンセルされましたのでお知らせいたします。
改めてのご予約をお待ちしております。`;

  await sendPlainTextEmail(to, "【ご予約キャンセルのお知らせ】", body);
}
