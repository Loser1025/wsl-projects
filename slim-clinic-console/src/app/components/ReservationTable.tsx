"use client";

import { useState } from "react";
import { ReservationRecord, ReservationSheetName, getCustomerName, getCustomerEmail, getMenuSummary, getCandidates, Candidate } from "@/app/components/types";

const SHEET_LABEL_MAP: Record<ReservationSheetName, string> = {
  "国内": "JP",
  "韓国": "KR",
  "台湾": "TW",
};

const QUESTIONNAIRE_URL_MAP: Record<ReservationSheetName, string> = {
  "国内": "https://surim-pre-questionnaire.pages.dev",
  "韓国": "https://surim-pre-questionnaire-kr.pages.dev",
  "台湾": "https://surim-pre-questionnaire-tw.pages.dev",
};

export default function ReservationTable({ records }: { records: ReservationRecord[] }) {
  const [loadingKey, setLoadingKey] = useState<string | null>(null);

  if (!records || records.length === 0) {
    return (
      <div className="rounded-lg border border-zinc-200 bg-white p-6 text-center text-zinc-500 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
        現在、未確定の申込みはありません
      </div>
    );
  }

  const handleConfirm = async (record: ReservationRecord, candidate: Candidate) => {
    const customerName = getCustomerName(record);
    const customerEmail = getCustomerEmail(record);
    const questionnaireUrl = QUESTIONNAIRE_URL_MAP[record.sheetName];

    if (!window.confirm(`${customerName} 様の予約を「${candidate.dateTime}」で確定しますか？`)) {
      return;
    }

    const key = `${record.sheetName}-${record.rowNumber}-${candidate.dateTime}`;
    setLoadingKey(key);

    try {
      await fetch("/api/reservations/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sheetName: record.sheetName,
          rowNumber: record.rowNumber,
          confirmedDateTime: candidate.dateTime,
          customerName,
          customerEmail,
          questionnaireUrl,
        }),
      });
    } catch {
      // 404やエラーでも仕様上許容されるため無視またはリロード
    } finally {
      setLoadingKey(null);
      window.location.reload();
    }
  };

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <table className="w-full text-left text-sm text-zinc-600 dark:text-zinc-300">
        <thead className="border-b border-zinc-200 bg-zinc-50 text-xs uppercase text-zinc-700 dark:border-zinc-800 dark:bg-zinc-800/50 dark:text-zinc-300">
          <tr>
            <th scope="col" className="px-4 py-3">地域</th>
            <th scope="col" className="px-4 py-3">氏名</th>
            <th scope="col" className="px-4 py-3">メールアドレス</th>
            <th scope="col" className="px-4 py-3">メニュー</th>
            <th scope="col" className="px-4 py-3">希望日時・確定操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {records.map((record) => {
            const name = getCustomerName(record);
            const email = getCustomerEmail(record);
            const menu = getMenuSummary(record);
            const candidates = getCandidates(record);
            const label = SHEET_LABEL_MAP[record.sheetName] || record.sheetName;

            return (
              <tr key={`${record.sheetName}-${record.rowNumber}`} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/50">
                <td className="px-4 py-3 font-medium">
                  <span className={`inline-block rounded px-2 py-0.5 text-xs font-semibold ${
                    record.sheetName === "国内" ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300" :
                    record.sheetName === "韓国" ? "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300" :
                    "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
                  }`}>
                    {label}
                  </span>
                </td>
                <td className="px-4 py-3 font-medium text-zinc-900 dark:text-zinc-100">{name}</td>
                <td className="px-4 py-3">{email}</td>
                <td className="px-4 py-3">{menu}</td>
                <td className="px-4 py-3">
                  {candidates.length === 0 ? (
                    <span className="text-zinc-400">希望日時なし</span>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {candidates.map((cand, idx) => {
                        const key = `${record.sheetName}-${record.rowNumber}-${cand.dateTime}`;
                        const isLoading = loadingKey === key;
                        return (
                          <button
                            key={idx}
                            onClick={() => handleConfirm(record, cand)}
                            disabled={isLoading}
                            className="inline-flex items-center rounded bg-zinc-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
                          >
                            {isLoading ? "処理中..." : `${cand.label}: ${cand.dateTime}`}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
