"use client";

import type { ReservationRecord } from "@/lib/sheets";

export default function ReservationTable({ records }: { records: ReservationRecord[] }) {
  return (
    <div className="p-6 bg-white rounded-lg shadow border border-zinc-200 text-zinc-500 text-sm">
      未確定の申込み ({records.length}件)
    </div>
  );
}
