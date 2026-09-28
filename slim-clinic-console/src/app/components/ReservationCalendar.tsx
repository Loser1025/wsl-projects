"use client";

import { useState } from "react";
import { ReservationRecord, ReservationSheetName, QUESTIONNAIRE_URL_MAP, getCustomerName, getCustomerEmail, getMenuSummary, getMeetLink } from "@/lib/reservation-fields";
import CustomerDetailModal from "@/app/components/CustomerDetailModal";

const SHEET_LABEL_MAP: Record<ReservationSheetName, string> = {
  "国内": "JP",
  "韓国": "KR",
  "台湾": "TW",
};

export default function ReservationCalendar({ records }: { records: ReservationRecord[] }) {
  const [currentDate, setCurrentDate] = useState(() => new Date());
  const [detailRecord, setDetailRecord] = useState<ReservationRecord | null>(null);

  const handleCancel = async (record: ReservationRecord, name: string) => {
    if (!window.confirm(`${name} 様の予約をキャンセルしますか？`)) return;
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
      window.location.reload();
    }
  };

  const handleNoShow = async (record: ReservationRecord, name: string) => {
    const meetLink = getMeetLink(record);
    const confirmMessage = meetLink
      ? `${name} 様を「無断キャンセル」扱いにしますか？(日程再調整メールが自動送信されます)`
      : `${name} 様を「無断キャンセル」扱いにしますか？(対面のため通知は送信されません)`;
    if (!window.confirm(confirmMessage)) return;
    try {
      await fetch("/api/reservations/no-show", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sheetName: record.sheetName,
          rowNumber: record.rowNumber,
          customerName: name,
          customerEmail: getCustomerEmail(record),
          meetLink,
        }),
      });
    } finally {
      window.location.reload();
    }
  };

  const handleReschedule = async (record: ReservationRecord, name: string) => {
    const currentDateTime = record.values["確定日時"] || "";
    const newDateTime = window.prompt(
      `${name} 様の新しい予約日時を入力してください(例: 2026-10-01 14:00)`,
      currentDateTime
    );
    if (!newDateTime || newDateTime.trim() === "" || newDateTime === currentDateTime) return;
    if (!window.confirm(`${name} 様の予約を「${newDateTime}」に変更し、お客様へ通知しますか？`)) return;

    try {
      await fetch("/api/reservations/reschedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sheetName: record.sheetName,
          rowNumber: record.rowNumber,
          newDateTime: newDateTime.trim(),
          customerName: name,
          customerEmail: getCustomerEmail(record),
          questionnaireUrl: QUESTIONNAIRE_URL_MAP[record.sheetName],
          meetLink: getMeetLink(record),
        }),
      });
    } finally {
      window.location.reload();
    }
  };

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();

  const firstDayOfMonth = new Date(year, month, 1);
  const lastDayOfMonth = new Date(year, month + 1, 0);
  const daysInMonth = lastDayOfMonth.getDate();
  const startingDayOfWeek = firstDayOfMonth.getDay();

  const prevMonth = () => {
    setCurrentDate(new Date(year, month - 1, 1));
  };

  const nextMonth = () => {
    setCurrentDate(new Date(year, month + 1, 1));
  };

  const calendarMap: Record<string, Array<{ record: ReservationRecord; time: string; name: string; menu: string; sheetLabel: string }>> = {};

  records.forEach((record) => {
    const confirmedDateTime = record.values["確定日時"] || "";
    if (!confirmedDateTime) return;

    const parts = confirmedDateTime.trim().split(/\s+/);
    if (parts.length < 2) return;

    const datePart = parts[0]; // YYYY-MM-DD
    const timePart = parts[1]; // HH:MM

    if (!calendarMap[datePart]) {
      calendarMap[datePart] = [];
    }

    calendarMap[datePart].push({
      record,
      time: timePart,
      name: getCustomerName(record),
      menu: getMenuSummary(record),
      sheetLabel: SHEET_LABEL_MAP[record.sheetName] || record.sheetName,
    });
  });

  const calendarDays = [];
  for (let i = 0; i < startingDayOfWeek; i++) {
    calendarDays.push(null);
  }
  for (let day = 1; day <= daysInMonth; day++) {
    const monthStr = String(month + 1).padStart(2, "0");
    const dayStr = String(day).padStart(2, "0");
    const dateKey = `${year}-${monthStr}-${dayStr}`;
    calendarDays.push({ day, dateKey, reservations: calendarMap[dateKey] || [] });
  }

  const weekDays = ["日", "月", "火", "水", "木", "金", "土"];

  return (
    <>
    <div className="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-800 dark:text-zinc-100">
          {year}年 {month + 1}月
        </h2>
        <div className="flex gap-2">
          <button
            onClick={prevMonth}
            className="rounded border border-zinc-300 px-3 py-1 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            前月
          </button>
          <button
            onClick={nextMonth}
            className="rounded border border-zinc-300 px-3 py-1 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            次月
          </button>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-1 text-center font-medium text-zinc-500 dark:text-zinc-400 text-xs mb-2">
        {weekDays.map((w, idx) => (
          <div key={idx} className={idx === 0 ? "text-red-500" : idx === 6 ? "text-blue-500" : ""}>
            {w}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 gap-1">
        {calendarDays.map((item, index) => {
          if (!item) {
            return <div key={index} className="h-28 rounded bg-zinc-50/50 dark:bg-zinc-800/20" />;
          }

          const { day, reservations } = item;

          return (
            <div
              key={index}
              className="h-28 overflow-y-auto rounded border border-zinc-100 bg-white p-1.5 text-left text-xs dark:border-zinc-800 dark:bg-zinc-900/50 flex flex-col"
            >
              <div className="font-semibold text-zinc-700 dark:text-zinc-300 mb-1">{day}</div>
              <div className="flex flex-col gap-1 overflow-y-auto">
                {reservations.map((res, rIdx) => (
                  <div
                    key={rIdx}
                    className="group rounded bg-zinc-100 px-1 py-0.5 dark:bg-zinc-800 text-[10px] leading-tight text-zinc-800 dark:text-zinc-200"
                    title={`${res.time} ${res.name} (${res.menu})`}
                  >
                    <span className="font-bold mr-1 text-indigo-600 dark:text-indigo-400">{res.sheetLabel}</span>
                    <span className="font-medium">{res.time}</span>{" "}
                    <button
                      onClick={() => setDetailRecord(res.record)}
                      className="hover:underline"
                    >
                      {res.name}
                    </button>
                    <span className="opacity-0 group-hover:opacity-100">
                      <button
                        onClick={() => handleReschedule(res.record, res.name)}
                        className="ml-1 text-amber-600 hover:underline dark:text-amber-400"
                      >
                        リスケ
                      </button>
                      <button
                        onClick={() => handleNoShow(res.record, res.name)}
                        className="ml-1 text-orange-600 hover:underline dark:text-orange-400"
                      >
                        バックレ
                      </button>
                      <button
                        onClick={() => handleCancel(res.record, res.name)}
                        className="ml-1 text-red-500 hover:underline"
                      >
                        取消
                      </button>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
    {detailRecord && (
      <CustomerDetailModal record={detailRecord} onClose={() => setDetailRecord(null)} />
    )}
    </>
  );
}
