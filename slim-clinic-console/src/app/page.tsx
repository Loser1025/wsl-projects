import { listAllReservationsGrouped } from "@/lib/sheets";
import ReservationStatusTabs from "@/app/components/ReservationStatusTabs";
import ReservationCalendar from "@/app/components/ReservationCalendar";

export const dynamic = "force-dynamic";

export default async function Page() {
  const { pending, confirmed, cancelled, noShow, pendingMatches } = await listAllReservationsGrouped();

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50 font-sans dark:bg-black">
      <header className="border-b border-zinc-200 bg-white px-6 py-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <h1 className="text-xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
          予約管理コンソール
        </h1>
      </header>
      <main className="flex-1 space-y-8 p-6 md:p-10 max-w-7xl mx-auto w-full">
        <section className="space-y-4">
          <h2 className="text-lg font-semibold text-zinc-800 dark:text-zinc-100">申し込み管理表</h2>
          <ReservationStatusTabs
            pending={pending}
            confirmed={confirmed}
            cancelled={cancelled}
            noShow={noShow}
            pendingMatches={pendingMatches}
          />
        </section>

        <section className="space-y-4">
          <h2 className="text-lg font-semibold text-zinc-800 dark:text-zinc-100">予約カレンダー</h2>
          <ReservationCalendar records={confirmed} />
        </section>
      </main>
    </div>
  );
}
