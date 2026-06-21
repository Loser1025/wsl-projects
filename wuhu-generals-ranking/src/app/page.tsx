// src/app/page.tsx
'use client';

import { General, GeneralStats } from '@/data/generals';
import TeamSection from '@/components/TeamSection';
import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';

function computeMaxStats(generals: General[]): GeneralStats {
  return generals.reduce<GeneralStats>(
    (max, g) => ({
      avgCases: Math.max(max.avgCases, g.stats.avgCases),
      bookingRate: Math.max(max.bookingRate, g.stats.bookingRate),
      avgCalls: Math.max(max.avgCalls, g.stats.avgCalls),
    }),
    { avgCases: 0, bookingRate: 0, avgCalls: 0 }
  );
}

export default function Home() {
  const [generals, setGenerals] = useState<General[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/generals')
      .then((res) => {
        if (!res.ok) throw new Error('データの取得に失敗しました');
        return res.json();
      })
      .then(setGenerals)
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400">
        エラー: {error}
      </div>
    );
  }

  if (!generals) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400">
        読み込み中...
      </div>
    );
  }

  const teamA = generals.filter((g) => g.team === 'A');
  const teamB = generals.filter((g) => g.team === 'B');
  const maxStats = computeMaxStats(generals);

  return (
    <div className="relative min-h-screen">
      {/* 多層背景 */}
      <div className="bg-aurora" />
      <div className="bg-layer" />
      <div className="bg-grid" />
      <div className="bg-light" />
      <div className="bg-streaks" />
      <div className="bg-ripple" />

      {/* 背景粒子 */}
      <div className="gold-particles" />

      {/* メインコンテンツ */}
      <div className="relative z-10 max-w-6xl mx-auto px-4 py-12">
        {/* ヘッダー */}
        <motion.header
          initial={{ opacity: 0, y: -30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
          className="text-center mb-16"
        >
          <h1 className="text-5xl md:text-7xl font-black tracking-[0.2em] text-gold title-glow mb-4">
            五虎大将軍制度
          </h1>
          <p className="text-gray-400 text-sm tracking-[0.5em] uppercase">
            Generals Ranking System
          </p>
          <div className="mt-6 h-px w-64 mx-auto bg-gradient-to-r from-transparent via-yellow-500/40 to-transparent" />
        </motion.header>

        {/* A隊セクション */}
        <div className="team-a-wrapper">
          <TeamSection
            teamLabel="甲 隊"
            teamSubLabel="大将軍 ／ 丞相 ／ 都督"
            generals={teamA}
            team="A"
            maxStats={maxStats}
          />
        </div>

        {/* セクション区切り */}
        <div className="flex items-center justify-center my-12 gap-4">
          <div className="h-px flex-1 max-w-32 bg-gradient-to-r from-transparent to-gray-700" />
          <span className="text-gray-600 text-xs tracking-[0.3em]">◆ ◆ ◆</span>
          <div className="h-px flex-1 max-w-32 bg-gradient-to-l from-transparent to-gray-700" />
        </div>

        {/* B隊セクション */}
        <div className="team-b-wrapper">
          <TeamSection
            teamLabel="乙 隊"
            teamSubLabel="一兵卒"
            generals={teamB}
            team="B"
            maxStats={maxStats}
          />
        </div>

        {/* フッター */}
        <footer className="text-center mt-20 pb-8">
          <p className="text-gray-600 text-xs tracking-widest">
            五虎大将軍制度 — Google Sheets連携対応
          </p>
        </footer>
      </div>
    </div>
  );
}
