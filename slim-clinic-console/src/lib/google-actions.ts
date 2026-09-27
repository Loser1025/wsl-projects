import { google } from "googleapis";
import { OAuth2Client } from "google-auth-library";
import { ReservationSheetName } from "@/lib/reservation-fields";

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

type EmailLanguage = "ja" | "ko" | "zh-TW";

function getEmailLanguage(sheetName: ReservationSheetName): EmailLanguage {
  if (sheetName === "韓国") return "ko";
  if (sheetName === "台湾") return "zh-TW";
  return "ja";
}

export type ConfirmationEmailInput = {
  to: string;
  customerName: string;
  confirmedDateTime: string;
  questionnaireUrl: string;
  meetLink?: string;
  sheetName: ReservationSheetName;
};

export async function sendConfirmationEmail(
  input: ConfirmationEmailInput
): Promise<void> {
  const isOnline = !!input.meetLink;
  const lang = getEmailLanguage(input.sheetName);

  const meetSections: Record<EmailLanguage, string> = {
    ja: isOnline
      ? `■ オンライン診療用リンク（Google Meet）
当日は下記URLよりご入室ください。
${input.meetLink}

`
      : `■ ご来院について
当日はクリニックまでご来院くださいませ。

`,
    ko: isOnline
      ? `■ 온라인 진료용 링크 (Google Meet)
당일 아래 URL로 입장해 주시기 바랍니다.
${input.meetLink}

`
      : `■ 내원 안내
당일 클리닉으로 내원해 주시기 바랍니다.

`,
    "zh-TW": isOnline
      ? `■ 線上看診連結(Google Meet)
當天請透過以下網址進入診間。
${input.meetLink}

`
      : `■ 關於來院
當天請直接前往診所。

`,
  };

  const bodies: Record<EmailLanguage, string> = {
    ja: `${input.customerName} 様

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

${meetSections.ja}ご不明な点やご不安な点がございましたら、
どうぞお気軽にお問い合わせくださいませ。

当日${input.customerName}様にお会いできますことを、
スタッフ一同心よりお待ち申し上げております。

今後とも何卒よろしくお願い申し上げます。`,
    ko: `${input.customerName} 님

평소 저희 클리닉을 아껴주셔서 진심으로 감사드립니다.
이번에 예약해 주셔서 대단히 감사합니다.

아래와 같이 예약이 확정되었음을 안내해 드립니다.

■ 예약 확정 일시
${input.confirmedDateTime}

■ 사전 문진표 작성 안내
번거로우시겠지만 당일 원활한 안내를 위해
내원(또는 온라인 진료 시작) 전까지 아래 URL에서
사전 문진표 작성을 부탁드립니다.
${input.questionnaireUrl}
※ 본 메일과 LINE으로 각각 안내를 드리고 있으나,
　사전 문진표 작성은 한 번만 해 주시면 됩니다.

${meetSections.ko}궁금하신 점이나 불안하신 점이 있으시면
언제든지 편하게 문의해 주시기 바랍니다.

당일 ${input.customerName}님을 뵙게 되기를
스태프 일동 진심으로 기다리고 있겠습니다.

앞으로도 잘 부탁드리겠습니다.`,
    "zh-TW": `${input.customerName} 您好

平時承蒙您的厚愛，由衷感謝。
非常感謝您這次的預約。

謹以此信通知您，您的預約已確定如下。

■ 預約確定日期時間
${input.confirmedDateTime}

■ 填寫術前問診表的請求
造成不便深感抱歉，為了讓您當天能順利看診，
請您在來院(或開始線上看診)前，
透過以下網址填寫術前問診表。
${input.questionnaireUrl}
※本郵件與LINE都會分別發送通知，
　但術前問診表只需填寫一次即可。

${meetSections["zh-TW"]}若有任何疑問或不安之處，
歡迎隨時與我們聯繫。

期待當天能與${input.customerName}見面，
全體工作人員由衷期待您的到來。

今後也請多多指教。`,
  };

  const subjects: Record<EmailLanguage, string> = {
    ja: "【ご予約確定のご案内】",
    ko: "【예약 확정 안내】",
    "zh-TW": "【預約確定通知】",
  };

  await sendPlainTextEmail(input.to, subjects[lang], bodies[lang]);
}

export type ReminderEmailInput = {
  to: string;
  customerName: string;
  confirmedDateTime: string;
  questionnaireUrl: string;
  meetLink?: string;
  sheetName: ReservationSheetName;
};

export async function sendReminderEmail(input: ReminderEmailInput): Promise<void> {
  const isOnline = !!input.meetLink;
  const lang = getEmailLanguage(input.sheetName);

  const meetSections: Record<EmailLanguage, string> = {
    ja: isOnline
      ? `■ オンライン診療用リンク（Google Meet）
まもなくのお時間になりましたら、下記URLよりご入室ください。
${input.meetLink}

`
      : `■ ご来院について
まもなくのお時間になりましたら、クリニックまでご来院くださいませ。

`,
    ko: isOnline
      ? `■ 온라인 진료용 링크 (Google Meet)
잠시 후 시간이 되면 아래 URL로 입장해 주시기 바랍니다.
${input.meetLink}

`
      : `■ 내원 안내
잠시 후 시간이 되면 클리닉으로 내원해 주시기 바랍니다.

`,
    "zh-TW": isOnline
      ? `■ 線上看診連結(Google Meet)
時間到後請透過以下網址進入診間。
${input.meetLink}

`
      : `■ 關於來院
時間到後請直接前往診所。

`,
  };

  const bodies: Record<EmailLanguage, string> = {
    ja: `${input.customerName} 様

まもなくご予約のお時間です。

■ ご予約日時
${input.confirmedDateTime}（10分後にご案内予定です）

${meetSections.ja}事前問診票のご入力がまだお済みでない場合は、
お手数ですが下記URLより当日までにご入力をお願いいたします。
${input.questionnaireUrl}

当日${input.customerName}様にお会いできますことを、
スタッフ一同心よりお待ち申し上げております。`,
    ko: `${input.customerName} 님

잠시 후 예약하신 시간입니다.

■ 예약 일시
${input.confirmedDateTime} (10분 후 안내 예정입니다)

${meetSections.ko}사전 문진표를 아직 작성하지 않으셨다면
번거로우시겠지만 당일 전까지 아래 URL에서 작성을 부탁드립니다.
${input.questionnaireUrl}

당일 ${input.customerName}님을 뵙게 되기를
스태프 일동 진심으로 기다리고 있겠습니다.`,
    "zh-TW": `${input.customerName} 您好

您的預約時間即將到來。

■ 預約日期時間
${input.confirmedDateTime}(將於10分鐘後為您服務)

${meetSections["zh-TW"]}若您尚未填寫術前問診表，
請於當天之前透過以下網址填寫。
${input.questionnaireUrl}

期待當天能與${input.customerName}見面，
全體工作人員由衷期待您的到來。`,
  };

  const subjects: Record<EmailLanguage, string> = {
    ja: "【まもなくご予約のお時間です】",
    ko: "【잠시 후 예약 시간입니다】",
    "zh-TW": "【預約時間即將到來】",
  };

  await sendPlainTextEmail(input.to, subjects[lang], bodies[lang]);
}

export type RescheduleEmailInput = {
  to: string;
  customerName: string;
  newDateTime: string;
  questionnaireUrl: string;
  meetLink?: string;
  sheetName: ReservationSheetName;
};

export async function sendRescheduleEmail(input: RescheduleEmailInput): Promise<void> {
  const isOnline = !!input.meetLink;
  const lang = getEmailLanguage(input.sheetName);

  const meetSections: Record<EmailLanguage, string> = {
    ja: isOnline
      ? `■ オンライン診療用リンク(Google Meet)
当日は下記URLよりご入室ください。
${input.meetLink}

`
      : `■ ご来院について
当日はクリニックまでご来院くださいませ。

`,
    ko: isOnline
      ? `■ 온라인 진료용 링크 (Google Meet)
당일 아래 URL로 입장해 주시기 바랍니다.
${input.meetLink}

`
      : `■ 내원 안내
당일 클리닉으로 내원해 주시기 바랍니다.

`,
    "zh-TW": isOnline
      ? `■ 線上看診連結(Google Meet)
當天請透過以下網址進入診間。
${input.meetLink}

`
      : `■ 關於來院
當天請直接前往診所。

`,
  };

  const bodies: Record<EmailLanguage, string> = {
    ja: `${input.customerName} 様

平素より格別のご高配を賜り、厚く御礼申し上げます。

ご予約の日時を、下記のとおり変更させていただきましたのでご案内申し上げます。

■ 変更後のご予約日時
${input.newDateTime}

■ 事前問診票のご入力のお願い
恐れ入りますが、ご来院(またはオンライン診療開始)前までに下記URLより
事前問診票のご入力をお願いいたします(すでにご入力済みの場合は改めてのご入力は不要です)。
${input.questionnaireUrl}

${meetSections.ja}ご不明な点やご不安な点がございましたら、
どうぞお気軽にお問い合わせくださいませ。

今後とも何卒よろしくお願い申し上げます。`,
    ko: `${input.customerName} 님

평소 저희 클리닉을 아껴주셔서 진심으로 감사드립니다.

예약 일시가 아래와 같이 변경되었음을 안내해 드립니다.

■ 변경 후 예약 일시
${input.newDateTime}

■ 사전 문진표 작성 안내
번거로우시겠지만 내원(또는 온라인 진료 시작) 전까지 아래 URL에서
사전 문진표 작성을 부탁드립니다 (이미 작성하신 경우 다시 작성하실 필요는 없습니다).
${input.questionnaireUrl}

${meetSections.ko}궁금하신 점이나 불안하신 점이 있으시면
언제든지 편하게 문의해 주시기 바랍니다.

앞으로도 잘 부탁드리겠습니다.`,
    "zh-TW": `${input.customerName} 您好

平時承蒙您的厚愛，由衷感謝。

謹通知您，您的預約時間已變更如下。

■ 變更後的預約日期時間
${input.newDateTime}

■ 填寫術前問診表的請求
造成不便深感抱歉，請您在來院(或開始線上看診)前，
透過以下網址填寫術前問診表(若您已填寫，則無需再次填寫)。
${input.questionnaireUrl}

${meetSections["zh-TW"]}若有任何疑問或不安之處，
歡迎隨時與我們聯繫。

今後也請多多指教。`,
  };

  const subjects: Record<EmailLanguage, string> = {
    ja: "【ご予約日時変更のご案内】",
    ko: "【예약 일시 변경 안내】",
    "zh-TW": "【預約時間變更通知】",
  };

  await sendPlainTextEmail(input.to, subjects[lang], bodies[lang]);
}

export type NoShowEmailInput = {
  to: string;
  customerName: string;
  meetLink: string;
  sheetName: ReservationSheetName;
};

export async function sendNoShowEmail(input: NoShowEmailInput): Promise<void> {
  const lang = getEmailLanguage(input.sheetName);

  const bodies: Record<EmailLanguage, string> = {
    ja: `お世話になっております。

スルリムクリニックでございます。

本日ご予約いただいておりましたオンライン診療につきまして、開始時間になってもご入室が確認できなかったため、今回の診察は改めて日時を調整させていただければと存じます。

再度の診察をご希望の場合は、お手数をおかけいたしますが、ご都合のよい日時を2〜3候補ほどお知らせいただけますでしょうか。

いただいた候補をもとに空き状況を確認し、改めて診察日時を調整させていただきます。

なお、今回の診察をキャンセルされる場合は、ご返信いただく必要はございません。

また、再予約後にご都合が悪くなった場合や、当日のご入室が難しい場合には、恐れ入りますが、事前にご連絡いただけますと幸いです。

お手数をおかけいたしますが、何卒よろしくお願いいたします🌷

スルリムクリニック
オンライン診療担当`,
    ko: `평소 신세를 지고 있습니다.

슬림 클리닉입니다.

금일 예약해 주신 온라인 진료와 관련하여, 시작 시간이 되어도 입장이 확인되지 않아 이번 진료는 일정을 다시 조정해 드리고자 합니다.

다시 진료를 원하실 경우, 번거로우시겠지만 편하신 날짜와 시간을 2~3개 정도 알려주시기 바랍니다.

보내주신 후보를 바탕으로 예약 가능 여부를 확인한 후, 다시 진료 일시를 조정해 드리겠습니다.

이번 진료를 취소하실 경우에는 별도로 답장하실 필요가 없습니다.

또한 재예약 후 사정이 어려워지신 경우나 당일 입장이 어려우신 경우에는 사전에 연락 주시면 감사하겠습니다.

번거로우시겠지만 잘 부탁드립니다🌷

슬림 클리닉
온라인 진료 담당`,
    "zh-TW": `平時承蒙您的關照。

我們是Surim診所。

關於您今日預約的線上看診，由於到了開始時間仍未確認您進入診間，這次的看診希望能重新協調時間。

若您希望再次看診，造成不便深感抱歉，請提供2~3個方便的日期時間供我們參考。

我們會根據您提供的候選時間確認可預約狀況，再重新為您安排看診時間。

若您要取消這次看診，則不需要回覆本郵件。

另外，重新預約後如有不便，或當天難以進入診間時，懇請您事先與我們聯繫。

造成不便深感抱歉，還請多多指教🌷

Surim診所
線上看診負責人`,
  };

  const subjects: Record<EmailLanguage, string> = {
    ja: "【診察日時再調整のお願い】",
    ko: "【진료 일정 조정 안내】",
    "zh-TW": "【看診時間調整通知】",
  };

  await sendPlainTextEmail(input.to, subjects[lang], bodies[lang]);
}

export async function cancelNotificationEmail(
  to: string,
  customerName: string,
  sheetName: ReservationSheetName
): Promise<void> {
  const lang = getEmailLanguage(sheetName);

  const bodies: Record<EmailLanguage, string> = {
    ja: `${customerName} 様

平素よりお世話になっております。

ご予約につきまして、キャンセルのお手続きが完了いたしましたので
ご連絡申し上げます。

またのご来院を心よりお待ち申し上げております。
改めてご予約をご希望の際は、どうぞお気軽にお申し込みくださいませ。

今後とも何卒よろしくお願い申し上げます。`,
    ko: `${customerName} 님

평소 신세를 지고 있습니다.

예약 취소 절차가 완료되었음을 알려드립니다.

다시 내원해 주실 날을 진심으로 기다리고 있겠습니다.
다시 예약을 원하실 경우 언제든지 편하게 신청해 주시기 바랍니다.

앞으로도 잘 부탁드리겠습니다.`,
    "zh-TW": `${customerName} 您好

平時承蒙您的關照。

謹通知您，您的預約取消手續已完成。

期待您再次光臨。
若之後希望重新預約，歡迎隨時與我們聯繫申請。

今後也請多多指教。`,
  };

  const subjects: Record<EmailLanguage, string> = {
    ja: "【ご予約キャンセルのご案内】",
    ko: "【예약 취소 안내】",
    "zh-TW": "【預約取消通知】",
  };

  await sendPlainTextEmail(to, subjects[lang], bodies[lang]);
}
