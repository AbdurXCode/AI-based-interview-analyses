import type { Metadata } from "next";

import { ClientProviders } from "@/components/ClientProviders";

import "./globals.css";

export const metadata: Metadata = {
  title: "PrepAI — Interview prep",
  description: "Resume analysis, JD fit scoring, and AI mock interviews",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ClientProviders>{children}</ClientProviders>
      </body>
    </html>
  );
}
