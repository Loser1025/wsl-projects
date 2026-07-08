'use client';

import { General, GeneralStats, GeneralTier } from '@/data/generals';
import GeneralCard from './GeneralCard';
import { motion } from 'framer-motion';
import Image from 'next/image';

interface TierSectionProps {
  tier: GeneralTier;
  teamLabel: string;
  subLabel: string;
  generals: General[];
  maxStats: GeneralStats;
  bgImage?: string;
}

const wrapperClass: Record<GeneralTier, string> = {
  shitenno: 'tier-shitenno-wrapper',
  busho: 'tier-busho-wrapper',
  heisotsu: 'tier-heisotsu-wrapper',
};

const headingClass: Record<GeneralTier, string> = {
  shitenno: 'text-yellow-400',
  busho: 'text-amber-200/90',
  heisotsu: 'text-gray-400',
};

export default function TierSection({ tier, teamLabel, subLabel, generals, maxStats, bgImage }: TierSectionProps) {
  if (generals.length === 0) return null;
  const isShitenno = tier === 'shitenno';

  return (
    <section className={`mb-16 ${wrapperClass[tier]}`}>
      {/* セクションヘッダー（背景は文字を楕円に囲むだけ透明フェード） */}
      <div className="relative mb-10 py-8">
        {bgImage && (
          <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-80 h-56 sm:w-96 sm:h-64 oval-fade-mask -z-10">
            <Image src={bgImage} alt="" fill sizes="384px" className="object-cover opacity-100" />
          </div>
        )}

        <motion.div
          initial={{ opacity: 0, y: -20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className={`text-center ${isShitenno ? 'mt-8' : ''}`}
        >
          <h2 className={`inline-block text-5xl md:text-6xl font-black tracking-[0.3em] ${headingClass[tier]}`}>
            {teamLabel}
          </h2>
          <p className="mt-2 text-xs tracking-[0.4em] text-gray-500 uppercase">{subLabel}</p>
          {isShitenno && (
            <div className="mt-3 h-px w-48 mx-auto bg-gradient-to-r from-transparent via-yellow-500/50 to-transparent" />
          )}
        </motion.div>
      </div>

      <div className="grid gap-6 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        {generals.map((general, i) => (
          <GeneralCard key={general.rank} general={general} index={i} maxStats={maxStats} />
        ))}
      </div>
    </section>
  );
}
