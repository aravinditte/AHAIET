import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "AHAIET — Ancient Hebrew & Aramaic Image-to-English Translator", description: "Translate Ancient Hebrew and Ancient Aramaic text captured from uploaded images into English, using local OCR and local translation models." };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (<html lang="en"><body className="bg-white text-neutral-900 dark:bg-neutral-900 dark:text-neutral-100">{children}</body></html>);
}
