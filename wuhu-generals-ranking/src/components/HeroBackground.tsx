'use client';

import { AnimatePresence, motion } from 'framer-motion';
import Image from 'next/image';
import { useEffect, useState } from 'react';

const HERO_IMAGES = [
  '/images/hero-general.png',
  '/images/battle-team-a.png',
  '/images/battle-team-b.png',
];

const ROTATE_INTERVAL_MS = 6000;

export default function HeroBackground() {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setIndex((i) => (i + 1) % HERO_IMAGES.length);
    }, ROTATE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <AnimatePresence>
      <motion.div
        key={HERO_IMAGES[index]}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 1.5, ease: 'easeInOut' }}
        className="absolute inset-0"
      >
        <Image
          src={HERO_IMAGES[index]}
          alt=""
          fill
          priority={index === 0}
          sizes="100vw"
          className="object-cover opacity-100"
        />
      </motion.div>
    </AnimatePresence>
  );
}
