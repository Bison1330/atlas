import type { Metadata, Viewport } from "next";
import { Fraunces, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

// Warm serif for marketing headlines. Used only via font-display on
// hero + scroll-narrative section headings; body stays in Inter.
const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Atlas — On your side when you build",
  description:
    "Describe your project in plain words. Get plans, 3D walkthroughs, real costs, and code checks — without hiring an architect or getting rolled by a contractor.",
  applicationName: "Atlas",
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: "#0B0D10",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrains.variable} ${fraunces.variable}`}
    >
      <body className="min-h-screen bg-bg-base font-sans text-text-primary antialiased">
        {children}
      </body>
    </html>
  );
}
