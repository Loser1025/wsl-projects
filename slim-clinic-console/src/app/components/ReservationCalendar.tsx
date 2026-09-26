"use client";

import type { ReservationRecord } from "@/lib/sheets";

export default function ReservationCalendar({ records }: { records: ReservationRecord[] }) {
  return (
    <div className="p-6 bg-white rounded-lg shadow border border-zinc-200 text-zinc-500 text-sm">
      確定済みの予約 ({records.length}件)
    </div>
  );
}
