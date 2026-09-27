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
  meetLink?: string;
};

export async function sendConfirmationEmail(
  input: ConfirmationEmailInput
): Promise<void> {
  const isOnline = !!input.meetLink;

  const meetSection = isOnline
    ? `■ オンライン診療用リンク（Google Meet）
当日は下記URLよりご入室ください。
${input.meetLink}

`
    : `■ ご来院について
当日はクリニックまでご来院くださいませ。

`;

  const body = `${input.customerName} 様

平素より格別のご高配を賜り、厚く御礼申し上げます。
このたびはご予約を賜り、誠にありがとうございます。

下記の内容にて、ご予約が確定いたしましたのでご案内申し上げます。

■ ご予約確定日時
${input.confirmedDateTime}

■ 事前問診票のご入力のお願い
恐れ入りますが、当日スムーズにご案内させていただくため、
ご来院（またはオンライン診療開始）前までに下記URLより
事前問診票のご入力をお願いいたします。
${input.questionnaireUrl}
※本メールとLINEの両方でご案内をお送りしておりますが、
　事前問診票のご入力は一回で結構です。

${meetSection}ご不明な点やご不安な点がございましたら、
どうぞお気軽にお問い合わせくださいませ。

当日${input.customerName}様にお会いできますことを、
スタッフ一同心よりお待ち申し上げております。

今後とも何卒よろしくお願い申し上げます。`;

  await sendPlainTextEmail(input.to, "【ご予約確定のご案内】", body);
}

export type ReminderEmailInput = {
  to: string;
  customerName: string;
  confirmedDateTime: string;
  questionnaireUrl: string;
  meetLink?: string;
};

export async function sendReminderEmail(input: ReminderEmailInput): Promise<void> {
  const isOnline = !!input.meetLink;

  const meetSection = isOnline
    ? `■ オンライン診療用リンク（Google Meet）
まもなくのお時間になりましたら、下記URLよりご入室ください。
${input.meetLink}

`
    : `■ ご来院について
まもなくのお時間になりましたら、クリニックまでご来院くださいませ。

`;

  const body = `${input.customerName} 様

まもなくご予約のお時間です。

■ ご予約日時
${input.confirmedDateTime}（10分後にご案内予定です）

${meetSection}事前問診票のご入力がまだお済みでない場合は、
お手数ですが下記URLより当日までにご入力をお願いいたします。
${input.questionnaireUrl}

当日${input.customerName}様にお会いできますことを、
スタッフ一同心よりお待ち申し上げております。`;

  await sendPlainTextEmail(input.to, "【まもなくご予約のお時間です】", body);
}

export async function cancelNotificationEmail(
  to: string,
  customerName: string
): Promise<void> {
  const body = `${customerName} 様

平素よりお世話になっております。

ご予約につきまして、キャンセルのお手続きが完了いたしましたので
ご連絡申し上げます。

またのご来院を心よりお待ち申し上げております。
改めてご予約をご希望の際は、どうぞお気軽にお申し込みくださいませ。

今後とも何卒よろしくお願い申し上げます。`;

  await sendPlainTextEmail(to, "【ご予約キャンセルのご案内】", body);
}
