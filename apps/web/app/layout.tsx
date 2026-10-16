import type { Metadata, Viewport } from "next";
import "./globals.css";

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
      <body className="min-h-screen" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
