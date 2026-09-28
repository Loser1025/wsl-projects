"use client";

import { useState } from "react";
import { ReservationRecord, ReservationSheetName, QUESTIONNAIRE_URL_MAP, getCustomerName, getCustomerEmail, getMenuSummary, getStaffNotes, getCandidates, getConfirmedDateTime, getMeetLink, isOnlineConsultation } from "@/lib/reservation-fields";

export type ReservationStatus = "pending" | "confirmed" | "cancelled" | "noShow";

const SHEET_LABEL_MAP: Record<ReservationSheetName, string> = {
  "国内": "JP",
  "韓国": "KR",
  "台湾": "TW",
};

const EMPTY_MESSAGE: Record<ReservationStatus, string> = {
  pending: "現在、未確定の申込みはありません",
  confirmed: "現在、確定済みの予約はありません",
  cancelled: "現在、確定前キャンセルはありません",
  noShow: "現在、バックレはありません",
};

export default function ReservationTable({
  records,
  status,
}: {
  records: ReservationRecord[];
  status: ReservationStatus;
}) {
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [customDateTimes, setCustomDateTimes] = useState<Record<string, string>>({});
  const [notesDrafts, setNotesDrafts] = useState<Record<string, string>>({});
  const [savingNotesKey, setSavingNotesKey] = useState<string | null>(null);

  if (!records || records.length === 0) {
    return (
      <div className="rounded-lg border border-zinc-200 bg-white p-6 text-center text-zinc-500 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
        {EMPTY_MESSAGE[status]}
      </div>
    );
  }

  const handleConfirm = async (record: ReservationRecord, dateTime: string) => {
    const customerName = getCustomerName(record);
    const customerEmail = getCustomerEmail(record);
    const questionnaireUrl = QUESTIONNAIRE_URL_MAP[record.sheetName];
    const isOnline = isOnlineConsultation(record);

    if (!window.confirm(`${customerName} 様の予約を「${dateTime}」で確定しますか？`)) {
      return;
    }

    const key = `${record.sheetName}-${record.rowNumber}-${dateTime}`;
    setLoadingKey(key);

    try {
      await fetch("/api/reservations/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sheetName: record.sheetName,
          rowNumber: record.rowNumber,
          confirmedDateTime: dateTime,
          customerName,
          customerEmail,
          questionnaireUrl,
          isOnline,
        }),
      });
    } catch {
      // 404やエラーでも仕様上許容されるため無視またはリロード
    } finally {
      setLoadingKey(null);
      window.location.reload();
    }
  };

  const handleCancelBeforeConfirm = async (record: ReservationRecord, name: string) => {
    if (!window.confirm(`${name} 様の申込みを確定前にキャンセルしますか？(お客様へキャンセルメールが送信されます)`)) {
      return;
    }

    const key = `${record.sheetName}-${record.rowNumber}-precancel`;
    setLoadingKey(key);

    try {
      await fetch("/api/reservations/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sheetName: record.sheetName,
          rowNumber: record.rowNumber,
          customerName: name,
          customerEmail: getCustomerEmail(record),
        }),
      });
    } finally {
      setLoadingKey(null);
      window.location.reload();
    }
  };

  const handleSaveNotes = async (record: ReservationRecord, rowKey: string, notes: string) => {
    setSavingNotesKey(rowKey);
    try {
      await fetch("/api/reservations/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sheetName: record.sheetName,
          rowNumber: record.rowNumber,
          notes,
        }),
      });
    } finally {
      setSavingNotesKey(null);
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
            <th scope="col" className="px-4 py-3">備考</th>
            {status === "pending" && (
              <>
                <th scope="col" className="px-4 py-3">希望日時・確定操作</th>
                <th scope="col" className="px-4 py-3">任意の日時で確定</th>
                <th scope="col" className="px-4 py-3">確定前キャンセル</th>
              </>
            )}
            {status !== "pending" && (
              <th scope="col" className="px-4 py-3">確定日時</th>
            )}
            {status === "confirmed" && (
              <th scope="col" className="px-4 py-3">Meetリンク</th>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {records.map((record) => {
            const name = getCustomerName(record);
            const email = getCustomerEmail(record);
            const menu = getMenuSummary(record);
            const candidates = status === "pending" ? getCandidates(record) : [];
            const label = SHEET_LABEL_MAP[record.sheetName] || record.sheetName;
            const rowKey = `${record.sheetName}-${record.rowNumber}`;
            const savedNotes = getStaffNotes(record);
            const notesValue = rowKey in notesDrafts ? notesDrafts[rowKey] : savedNotes;
            const isSavingNotes = savingNotesKey === rowKey;
            const customValue = customDateTimes[rowKey] || "";
            const customKey = customValue ? `${rowKey}-${customValue.replace("T", " ")}` : null;
            const customIsLoading = customKey !== null && loadingKey === customKey;
            const precancelKey = `${rowKey}-precancel`;
            const precancelIsLoading = loadingKey === precancelKey;

            return (
              <tr key={rowKey} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/50">
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
                  <div className="flex flex-col gap-1">
                    <textarea
                      value={notesValue}
                      onChange={(e) =>
                        setNotesDrafts((prev) => ({ ...prev, [rowKey]: e.target.value }))
                      }
                      rows={2}
                      className="w-40 rounded border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
                    />
                    <button
                      onClick={() => handleSaveNotes(record, rowKey, notesValue)}
                      disabled={isSavingNotes || notesValue === savedNotes}
                      className="self-start rounded bg-zinc-200 px-2 py-0.5 text-[11px] font-medium text-zinc-700 hover:bg-zinc-300 disabled:opacity-40 dark:bg-zinc-700 dark:text-zinc-200"
                    >
                      {isSavingNotes ? "保存中..." : "保存"}
                    </button>
                  </div>
                </td>
                {status === "pending" && (
                  <>
                    <td className="px-4 py-3">
                      {candidates.length === 0 ? (
                        <span className="text-zinc-400">希望日時なし</span>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          {candidates.map((cand, idx) => {
                            const key = `${rowKey}-${cand.dateTime}`;
                            const isLoading = loadingKey === key;
                            return (
                              <button
                                key={idx}
                                onClick={() => handleConfirm(record, cand.dateTime)}
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
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <input
                          type="datetime-local"
                          value={customValue}
                          onChange={(e) =>
                            setCustomDateTimes((prev) => ({ ...prev, [rowKey]: e.target.value }))
                          }
                          className="rounded border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
                        />
                        <button
                          onClick={() => handleConfirm(record, customValue.replace("T", " "))}
                          disabled={!customValue || customIsLoading}
                          className="inline-flex items-center rounded bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
                        >
                          {customIsLoading ? "処理中..." : "この日時で確定"}
                        </button>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => handleCancelBeforeConfirm(record, name)}
                        disabled={precancelIsLoading}
                        className="inline-flex items-center rounded bg-red-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-500 disabled:opacity-40"
                      >
                        {precancelIsLoading ? "処理中..." : "キャンセル"}
                      </button>
                    </td>
                  </>
                )}
                {status !== "pending" && (
                  <td className="px-4 py-3">{getConfirmedDateTime(record) || "-"}</td>
                )}
                {status === "confirmed" && (
                  <td className="px-4 py-3">
                    {getMeetLink(record) ? (
                      <a
                        href={getMeetLink(record)}
                        target="_blank"
                        rel="noreferrer"
                        className="text-indigo-600 hover:underline dark:text-indigo-400"
                      >
                        Meetリンク
                      </a>
                    ) : (
                      <span className="text-zinc-400">対面</span>
                    )}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
