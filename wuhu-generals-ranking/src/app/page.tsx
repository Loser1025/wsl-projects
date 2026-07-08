// src/app/page.tsx
'use client';

import { General, GeneralStats } from '@/data/generals';
import TierSection from '@/components/TierSection';
import HeroBackground from '@/components/HeroBackground';
import ThreeBackground from '@/components/ThreeBackground';
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

  const shitenno = generals.filter((g) => g.tier === 'shitenno');
  const busho = generals.filter((g) => g.tier === 'busho');
  const heisotsu = generals.filter((g) => g.tier === 'heisotsu');
  const maxStats = computeMaxStats(generals);

  return (
    <div className="relative min-h-screen">
      {/* 3D背景（Three.js 戦場演出） */}
      <ThreeBackground />

      {/* メインコンテンツ */}
      <div className="relative z-10 max-w-6xl mx-auto px-4 py-12">
        {/* ヒーローヘッダー */}
        <div className="relative overflow-hidden mb-16">
          <div className="absolute inset-0 radial-fade-mask">
            <HeroBackground />
            <div className="absolute inset-0 bg-gradient-to-b from-black/30 via-black/55 to-ink" />
          </div>
          <motion.header
            initial={{ opacity: 0, y: -30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
            className="relative z-10 text-center py-24 px-4"
          >
            <h1 className="text-5xl md:text-7xl font-black tracking-[0.2em] text-gold title-glow mb-4">
              五虎大将軍制度
            </h1>
            <p className="text-gray-300 text-sm tracking-[0.5em] uppercase">
              Generals Ranking System
            </p>
            <div className="mt-6 h-px w-64 mx-auto bg-gradient-to-r from-transparent via-yellow-500/40 to-transparent" />
          </motion.header>
        </div>

        {/* 四天王セクション（1〜4位） */}
        <TierSection
          tier="shitenno"
          teamLabel="四 天 王"
          subLabel={`Shitennō — Rank 1-${shitenno.length}`}
          generals={shitenno}
          maxStats={maxStats}
          bgImage="/images/battle-team-a.png"
        />

        {/* セクション区切り */}
        <div className="flex items-center justify-center my-12 gap-4">
          <div className="h-px flex-1 max-w-32 bg-gradient-to-r from-transparent to-gray-700" />
          <span className="text-gray-600 text-xs tracking-[0.3em]">◆ ◆ ◆</span>
          <div className="h-px flex-1 max-w-32 bg-gradient-to-l from-transparent to-gray-700" />
        </div>

        {/* 武将セクション（5〜8位） */}
        <TierSection
          tier="busho"
          teamLabel="武 将"
          subLabel={`Busho — Rank ${shitenno.length + 1}-${shitenno.length + busho.length}`}
          generals={busho}
          maxStats={maxStats}
          bgImage="/images/battle-team-b.png"
        />

        {/* セクション区切り */}
        <div className="flex items-center justify-center my-12 gap-4">
          <div className="h-px flex-1 max-w-32 bg-gradient-to-r from-transparent to-gray-700" />
          <span className="text-gray-600 text-xs tracking-[0.3em]">◆ ◆ ◆</span>
          <div className="h-px flex-1 max-w-32 bg-gradient-to-l from-transparent to-gray-700" />
        </div>

        {/* 一兵卒セクション（9位以降・無制限） */}
        <TierSection
          tier="heisotsu"
          teamLabel="一 兵 卒"
          subLabel={`Heisotsu — Rank ${shitenno.length + busho.length + 1}+ (${heisotsu.length}名)`}
          generals={heisotsu}
          maxStats={maxStats}
        />

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
