// src/app/layout.tsx
import type { Metadata } from "next";
import { Noto_Serif_JP } from "next/font/google";
import "./globals.css";

const notoSerifJP = Noto_Serif_JP({
  variable: "--font-noto-serif-jp",
  subsets: ["latin"],
  weight: ["400", "700", "900"],
});

export const metadata: Metadata = {
  title: "五虎大将軍制度 - 三国志ランキング",
  description: "三国志モチーフの武将ランキング。五虎大将軍制度によるA隊・B隊のランキング表示。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="ja"
      className={`${notoSerifJP.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-ink">{children}</body>
    </html>
  );
}
