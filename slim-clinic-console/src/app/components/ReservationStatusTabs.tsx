"use client";

import { useState } from "react";
import { ReservationRecord } from "@/lib/reservation-fields";
import ReservationTable, { ReservationStatus } from "@/app/components/ReservationTable";

const TAB_LABELS: Record<ReservationStatus, string> = {
  pending: "未確定",
  confirmed: "確定",
  cancelled: "キャンセル",
  noShow: "無断キャンセル",
};

const TAB_ORDER: ReservationStatus[] = ["pending", "confirmed", "cancelled", "noShow"];

export default function ReservationStatusTabs({
  pending,
  confirmed,
  cancelled,
  noShow,
}: {
  pending: ReservationRecord[];
  confirmed: ReservationRecord[];
  cancelled: ReservationRecord[];
  noShow: ReservationRecord[];
}) {
  const [activeTab, setActiveTab] = useState<ReservationStatus>("pending");

  const groups: Record<ReservationStatus, ReservationRecord[]> = {
    pending,
    confirmed,
    cancelled,
    noShow,
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {TAB_ORDER.map((key) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
              activeTab === key
                ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
            }`}
          >
            {TAB_LABELS[key]} ({groups[key].length})
          </button>
        ))}
      </div>
      <ReservationTable records={groups[activeTab]} status={activeTab} />
    </div>
  );
}
