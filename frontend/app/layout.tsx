import type { Metadata } from "next";
import "./globals.css";
import { AppProvider } from "@/context/AppContext";
import { HtmlLang } from "@/components/ui/HtmlLang";

export const metadata: Metadata = {
  title: "AI Werewolf",
  description: "AI Werewolf Spectator Console",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen">
        <AppProvider>
          <HtmlLang />
          {children}
        </AppProvider>
      </body>
    </html>
  );
}
