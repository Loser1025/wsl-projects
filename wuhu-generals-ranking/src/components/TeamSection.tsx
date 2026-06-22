'use client';

import { General, GeneralStats } from '@/data/generals';
import GeneralCard from './GeneralCard';
import { motion } from 'framer-motion';
import Image from 'next/image';

interface TeamSectionProps {
  teamLabel: string;
  generals: General[];
  team: 'A' | 'B';
  maxStats: GeneralStats;
  bgImage: string;
}

export default function TeamSection({ teamLabel, generals, team, maxStats, bgImage }: TeamSectionProps) {
  const isTeamA = team === 'A';

  return (
    <section className="mb-16">
      {/* セクションヘッダー（背景は文字を楕円に囲むだけ透明フェード） */}
      <div className="relative mb-10 py-8">
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-80 h-56 sm:w-96 sm:h-64 oval-fade-mask -z-10">
          <Image src={bgImage} alt="" fill sizes="384px" className="object-cover opacity-100" />
        </div>

        <motion.div
          initial={{ opacity: 0, y: -20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className={`text-center ${isTeamA ? 'mt-8' : ''}`}
        >
          <h2 className={`inline-block text-5xl md:text-6xl font-black tracking-[0.3em] ${isTeamA ? 'text-yellow-400' : 'text-gray-300'}`}>
            {teamLabel}
          </h2>
          {isTeamA && (
            <div className="mt-3 h-px w-48 mx-auto bg-gradient-to-r from-transparent via-yellow-500/50 to-transparent" />
          )}
        </motion.div>
      </div>

      {/* カードグリッド */}
      <div className={`
        grid gap-6
        ${isTeamA
          ? 'grid-cols-1 md:grid-cols-3'
          : 'grid-cols-1 sm:grid-cols-3'
        }
      `}>
        {generals.map((general, i) => (
          <GeneralCard key={general.rank} general={general} index={i} maxStats={maxStats} />
        ))}
      </div>
    </section>
  );
}
