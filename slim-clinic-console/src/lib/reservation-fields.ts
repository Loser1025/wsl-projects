export const RESERVATION_SHEET_NAMES = ["国内", "韓国", "台湾"] as const;
export type ReservationSheetName = typeof RESERVATION_SHEET_NAMES[number];

export type ReservationRecord = {
  sheetName: ReservationSheetName;
  rowNumber: number;
  values: Record<string, string>;
};

export type Candidate = { label: string; dateTime: string };

type SheetFieldMapping = {
  name: string;
  email: string;
  menu: string;
  candidates:
    | { type: "combined"; field: string }
    | { type: "separate"; pairs: [string, string][] };
};

// 実際のシートのヘッダー行(2026-09-26に実データを確認済み)に基づく。
// 国内・台湾は希望日時が1列に結合された文字列、韓国のみ列が分かれている。
const SHEET_FIELD_MAP: Record<ReservationSheetName, SheetFieldMapping> = {
  "国内": {
    name: "お名前",
    email: "メールアドレス",
    menu: "ご希望メニュー",
    candidates: { type: "combined", field: "ご希望日時" },
  },
  "台湾": {
    name: "姓名",
    email: "電子信箱",
    menu: "看診項目",
    candidates: { type: "combined", field: "希望時段" },
  },
  "韓国": {
    name: "이름",
    email: "이메일",
    menu: "희망 메뉴",
    candidates: {
      type: "separate",
      pairs: [
        ["제1희망 날짜", "제1희망 시간"],
        ["제2희망 날짜", "제2희망 시간"],
        ["제3희망 날짜", "제3희망 시간"],
      ],
    },
  },
};

export function getCustomerName(record: ReservationRecord): string {
  return record.values[SHEET_FIELD_MAP[record.sheetName].name] || "";
}

export function getCustomerEmail(record: ReservationRecord): string {
  return record.values[SHEET_FIELD_MAP[record.sheetName].email] || "";
}

export function getMenuSummary(record: ReservationRecord): string {
  return record.values[SHEET_FIELD_MAP[record.sheetName].menu] || "";
}

export function getStaffNotes(record: ReservationRecord): string {
  return record.values["スタッフ備考"] || "";
}

// 韓国シートには電話番号列が存在しないため、意図的にマッピングを持たない(取得結果は常に空文字)
const PHONE_FIELD: Partial<Record<ReservationSheetName, string>> = {
  "国内": "お電話番号",
  "台湾": "電話號碼",
};

export function getCustomerPhone(record: ReservationRecord): string {
  const field = PHONE_FIELD[record.sheetName];
  return field ? record.values[field] || "" : "";
}

const CONSULTATION_TYPE_FIELD: Record<ReservationSheetName, { field: string; onlineValue: string }> = {
  "国内": { field: "診察形式", onlineValue: "オンライン診察" },
  "台湾": { field: "看診方式", onlineValue: "線上看診" },
  "韓国": { field: "진료 형식", onlineValue: "온라인 진료" },
};

export function isOnlineConsultation(record: ReservationRecord): boolean {
  const mapping = CONSULTATION_TYPE_FIELD[record.sheetName];
  return record.values[mapping.field] === mapping.onlineValue;
}

export function getConfirmedDateTime(record: ReservationRecord): string {
  return record.values["確定日時"] || "";
}

export function getMeetLink(record: ReservationRecord): string {
  return record.values["Meetリンク"] || "";
}

export function getReminderSentFlag(record: ReservationRecord): boolean {
  return (record.values["リマインド送信済み"] || "").trim() !== "";
}

// 確定日時列は候補文字列をそのまま転記したもので、区切り文字(-/)や時刻欠落など表記ゆれがあるため緩く抽出する。
// 時刻が取れない場合はリマインド対象外としてnullを返す。
export function parseConfirmedDateTime(value: string): Date | null {
  const dateMatch = value.match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
  const timeMatch = value.match(/(\d{1,2}):(\d{2})/);
  if (!dateMatch || !timeMatch) return null;

  const [, y, mo, d] = dateMatch;
  const [, h, mi] = timeMatch;
  // シート上の日時はJST前提。JSTの壁時計時刻をUTCへ変換するため9時間引く。
  return new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h) - 9, Number(mi)));
}

export const QUESTIONNAIRE_URL_MAP: Record<ReservationSheetName, string> = {
  "国内": "https://surim-pre-questionnaire.pages.dev",
  "韓国": "https://surim-pre-questionnaire-kr.pages.dev",
  "台湾": "https://surim-pre-questionnaire-tw.pages.dev",
};

export function getCandidates(record: ReservationRecord): Candidate[] {
  const mapping = SHEET_FIELD_MAP[record.sheetName].candidates;

  if (mapping.type === "combined") {
    const raw = record.values[mapping.field] || "";
    return raw
      .split("/")
      .map((segment) => segment.trim())
      .filter(Boolean)
      .map((segment) => {
        const idx = segment.indexOf(":");
        if (idx === -1) return { label: segment, dateTime: segment };
        return {
          label: segment.slice(0, idx).trim(),
          dateTime: segment.slice(idx + 1).trim(),
        };
      });
  }

  const candidates: Candidate[] = [];
  mapping.pairs.forEach(([dateField, timeField], i) => {
    const date = record.values[dateField];
    const time = record.values[timeField];
    if (date && time) {
      candidates.push({ label: `第${i + 1}希望`, dateTime: `${date} ${time}` });
    }
  });
  return candidates;
}
