export type ReservationSheetName = "国内" | "韓国" | "台湾";
export type ReservationRecord = { sheetName: ReservationSheetName; rowNumber: number; values: Record<string, string>; };
export type Candidate = { label: string; dateTime: string };

const SHEET_FIELD_MAP: Record<ReservationSheetName, { name: string; email: string; menu: string; candidates: any }> = {
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

export function getCandidates(record: ReservationRecord): Candidate[] {
  const mapping = SHEET_FIELD_MAP[record.sheetName].candidates;
  const candidates: Candidate[] = [];
  if (mapping.type === "combined") {
    const val = record.values[mapping.field] || "";
    if (val.trim()) {
      candidates.push({ label: val.trim(), dateTime: val.trim() });
    }
  } else {
    for (const [dateField, timeField] of mapping.pairs) {
      const d = record.values[dateField] || "";
      const t = record.values[timeField] || "";
      if (d.trim() && t.trim()) {
        const dt = `${d.trim()} ${t.trim()}`;
        candidates.push({ label: dt, dateTime: dt });
      }
    }
  }
  return candidates;
}
