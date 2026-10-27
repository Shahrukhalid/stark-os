import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ThemeSync } from "@/components/ThemeSync";

// Runs before first paint so the saved theme applies on every screen without a dark flash.
const THEME_INIT = `try{var t=localStorage.getItem('stark-theme')||'system';if(t==='system')t=matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';document.documentElement.dataset.theme=t;document.documentElement.style.colorScheme=t}catch(e){}`;

export const metadata: Metadata = {
  title: "STARK OS",
  description: "Project Genesis: a governed multi-agent social media team",
};

export const viewport: Viewport = { themeColor: "#06080b", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: browser extensions (e.g. security/ad-block add-ons) inject attributes such as
    // bis_register into <html>/<body> before React loads. It only silences attribute mismatches on these two tags.
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body className="min-h-screen" suppressHydrationWarning>
        <ThemeSync />
        {children}
      </body>
    </html>
  );
}
