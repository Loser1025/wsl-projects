import type { ReservationRecord } from "@/lib/sheets";
import ReservationTable from "@/app/components/ReservationTable";
import ReservationCalendar from "@/app/components/ReservationCalendar";

export default function Page() {
  const pendingRecords: ReservationRecord[] = [];
  const confirmedRecords: ReservationRecord[] = [];

  return (
    <div className="min-h-screen bg-zinc-100 text-zinc-900 flex flex-col">
      <header className="bg-white border-b border-zinc-200 px-6 py-4 shadow-xs">
        <h1 className="text-xl font-bold text-zinc-800">予約管理コンソール</h1>
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto p-6 flex flex-col gap-8">
        <section className="flex flex-col gap-4">
          <h2 className="text-lg font-bold text-zinc-800 flex items-center gap-2">
            <span>申し込み管理表</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 font-semibold">
              未確定: {pendingRecords.length}件
            </span>
          </h2>
          <ReservationTable records={pendingRecords} />
        </section>

        <section className="flex flex-col gap-4">
          <h2 className="text-lg font-bold text-zinc-800 flex items-center gap-2">
            <span>予約カレンダー</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 font-semibold">
              確定済み: {confirmedRecords.length}件
            </span>
          </h2>
          <ReservationCalendar records={confirmedRecords} />
        </section>
      </main>
    </div>
  );
}
