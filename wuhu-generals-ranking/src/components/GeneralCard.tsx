'use client';

import { General, GeneralStats } from '@/data/generals';
import { motion } from 'framer-motion';
import { Shield, Brain, Crown } from 'lucide-react';
import Image from 'next/image';
import { useState } from 'react';

const titleColors: Record<string, string> = {
  '大将軍': 'bg-gradient-to-r from-yellow-400 via-amber-300 to-yellow-500 text-black',
  '丞相': 'bg-gradient-to-r from-purple-500 via-violet-400 to-purple-600 text-white',
  '都督': 'bg-gradient-to-r from-blue-500 via-cyan-400 to-blue-600 text-white',
  '一兵卒': 'bg-gradient-to-r from-gray-500 via-gray-400 to-gray-600 text-white',
};

const statConfig = [
  { key: 'avgCases' as const, label: 'アベ受任', icon: Shield, gradient: 'from-red-600 to-red-400', bg: 'bg-red-950', format: (v: number) => v.toFixed(2) },
  { key: 'bookingRate' as const, label: '予約率', icon: Brain, gradient: 'from-blue-600 to-blue-400', bg: 'bg-blue-950', format: (v: number) => `${v.toFixed(1)}%` },
  { key: 'avgCalls' as const, label: 'アベコール数', icon: Crown, gradient: 'from-green-600 to-green-400', bg: 'bg-green-950', format: (v: number) => v.toFixed(1) },
];

export default function GeneralCard({ general, index, maxStats }: { general: General; index: number; maxStats: GeneralStats }) {
  const isTeamA = general.team === 'A';
  const [imgLoaded, setImgLoaded] = useState(false);
  const [imgError, setImgError] = useState(false);
  const [objectPosition, setObjectPosition] = useState('center');
  const fallbackSrc = `https://picsum.photos/seed/${encodeURIComponent(general.name)}/400/250`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 60, scale: 0.9 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.6, delay: index * 0.15, ease: 'easeOut' }}
      whileHover={isTeamA ? { rotateY: 8, rotateX: -4, scale: 1.04, z: 40 } : { scale: 1.03 }}
      className={`
        relative group rounded-2xl border overflow-hidden
        ${isTeamA
          ? 'border-yellow-500/50 bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 shadow-[0_0_30px_rgba(234,179,8,0.15)]'
          : 'border-gray-700/50 bg-gradient-to-br from-gray-900 to-gray-800 shadow-lg'
        }
        transition-shadow duration-300
        ${isTeamA ? 'hover:shadow-[0_0_50px_rgba(234,179,8,0.3)]' : 'hover:shadow-[0_0_20px_rgba(255,255,255,0.08)]'}
      `}
      style={{ perspective: 800 }}
    >
      {/* 背景装飾：和風パターン */}
      <div className="absolute inset-0 opacity-5 pointer-events-none"
        style={{
          backgroundImage: `repeating-linear-gradient(45deg, transparent, transparent 10px, rgba(255,215,0,0.1) 10px, rgba(255,215,0,0.1) 11px)`,
        }}
      />

      {/* ===== 画像エリア ===== */}
      <div className="relative w-full h-[200px] overflow-hidden rounded-t-[12px]">
        {/* スケルトンスクリーン */}
        {!imgLoaded && (
          <div className="absolute inset-0 z-0 animate-pulse bg-gradient-to-br from-gray-800 via-gray-700 to-gray-800" />
        )}

        {/* 画像 */}
        <div className="relative w-full h-full overflow-hidden">
          <Image
            src={imgError ? fallbackSrc : general.imageUrl}
            alt={general.name}
            width={400}
            height={250}
            className={`
              object-cover w-full h-full
              transition-transform duration-500 ease-out
              group-hover:scale-105
              ${imgLoaded ? 'opacity-100' : 'opacity-0'}
            `}
            style={{ transition: 'opacity 0.5s, transform 0.5s ease-out', objectPosition }}
            onLoad={(e) => {
              setImgLoaded(true);
              const img = e.currentTarget;
              if (img.naturalHeight > img.naturalWidth) {
                setObjectPosition('center 40%');
              }
            }}
            onError={() => setImgError(true)}
            priority={index < 3}
          />
        </div>

        {/* 画像オーバーレイグラデーション（上: 透明 → 下: 暗い） */}
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-gray-900/90 pointer-events-none" />

        {/* 武将名オーバーレイ（画像下部） */}
        <div className="absolute bottom-2 left-0 right-0 text-center pointer-events-none z-10">
          <span className={`text-lg font-bold tracking-widest drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)] ${isTeamA ? 'text-yellow-100' : 'text-gray-200'}`}>
            {general.name}
          </span>
        </div>

        {/* 順位バッジ（画像上に重ねる） */}
        <div className="absolute top-3 left-3 z-10">
          <div className={`
            flex items-center justify-center w-10 h-10 rounded-full font-bold text-lg
            ${isTeamA
              ? 'bg-gradient-to-br from-yellow-400 to-amber-600 text-black shadow-lg shadow-yellow-500/30'
              : 'bg-gradient-to-br from-gray-600 to-gray-700 text-gray-200 shadow-md'
            }
          `}>
            {general.rank}
          </div>
        </div>

        {/* 称号バッジ（画像上に重ねる） */}
        <div className="absolute top-3 right-3 z-10">
          <span className={`px-4 py-1.5 rounded-full text-base font-bold tracking-wider ${titleColors[general.title]}`}>
            {general.title}
          </span>
        </div>

        {/* 金色の光彩（A隊のみ） */}
        {isTeamA && (
          <div className="absolute inset-0 rounded-t-[12px] pointer-events-none shadow-[inset_0_0_20px_rgba(234,179,8,0.15)]" />
        )}
      </div>

      {/* ===== カード本体（ステータス） ===== */}
      <div className="p-6">
        {/* ステータス */}
        <div className="space-y-3">
          {statConfig.map(({ key, label, icon: Icon, gradient, bg, format }) => {
            const max = maxStats[key] || 1;
            const percent = Math.min((general.stats[key] / max) * 100, 100);
            return (
              <div key={key} className="flex items-center gap-2">
                <div className={`flex items-center gap-1 w-20 text-xs text-gray-400 ${bg} rounded px-2 py-1`}>
                  <Icon size={12} />
                  <span>{label}</span>
                </div>
                <div className="flex-1 h-3 bg-gray-800 rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    whileInView={{ width: `${percent}%` }}
                    viewport={{ once: true }}
                    transition={{ duration: 1, delay: index * 0.15 + 0.3, ease: 'easeOut' }}
                    className={`h-full rounded-full bg-gradient-to-r ${gradient}`}
                  />
                </div>
                <span className="w-12 text-right text-xs font-mono text-gray-300">
                  {format(general.stats[key])}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* A隊カード：下部の金色ライン */}
      {isTeamA && (
        <div className="h-1 bg-gradient-to-r from-transparent via-yellow-400 to-transparent" />
      )}
    </motion.div>
  );
}
