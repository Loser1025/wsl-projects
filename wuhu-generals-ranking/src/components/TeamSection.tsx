'use client';

import { General } from '@/data/generals';
import GeneralCard from './GeneralCard';
import { motion } from 'framer-motion';

interface TeamSectionProps {
  teamLabel: string;
  teamSubLabel: string;
  generals: General[];
  team: 'A' | 'B';
}

export default function TeamSection({ teamLabel, teamSubLabel, generals, team }: TeamSectionProps) {
  const isTeamA = team === 'A';

  return (
    <section className="mb-16">
      {/* セクションヘッダー */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5 }}
        className="text-center mb-10"
      >
        <h2 className={`inline-block text-3xl font-bold tracking-[0.3em] ${isTeamA ? 'text-yellow-400' : 'text-gray-400'}`}>
          {teamLabel}
        </h2>
        <p className="text-base text-gray-500 mt-2 tracking-widest">{teamSubLabel}</p>
        {isTeamA && (
          <div className="mt-3 h-px w-48 mx-auto bg-gradient-to-r from-transparent via-yellow-500/50 to-transparent" />
        )}
      </motion.div>

      {/* カードグリッド */}
      <div className={`
        grid gap-6
        ${isTeamA
          ? 'grid-cols-1 md:grid-cols-3'
          : 'grid-cols-1 sm:grid-cols-3'
        }
      `}>
        {generals.map((general, i) => (
          <GeneralCard key={general.rank} general={general} index={i} />
        ))}
      </div>
    </section>
  );
}
