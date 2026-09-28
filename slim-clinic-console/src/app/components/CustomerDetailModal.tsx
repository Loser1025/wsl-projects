"use client";

import { ReservationRecord } from "@/lib/reservation-fields";

export default function CustomerDetailModal({
  record,
  onClose,
}: {
  record: ReservationRecord;
  onClose: () => void;
}) {
  const entries = Object.entries(record.values).filter(([, value]) => value);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-md overflow-y-auto rounded-lg bg-white p-5 shadow-xl dark:bg-zinc-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">お客様詳細</h3>
          <button
            onClick={onClose}
            className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
          >
            ✕
          </button>
        </div>
        <dl className="space-y-3 text-sm">
          {entries.map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs font-medium text-zinc-400 dark:text-zinc-500">{label}</dt>
              <dd className="whitespace-pre-wrap break-words text-zinc-800 dark:text-zinc-100">
                {value}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
