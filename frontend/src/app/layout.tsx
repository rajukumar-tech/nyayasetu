import type { Metadata, Viewport } from "next";
import { Noto_Sans, Noto_Sans_Devanagari, Noto_Sans_Kannada } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/Providers";

const noto = Noto_Sans({ variable: "--font-noto", subsets: ["latin"], weight: ["400", "500", "600", "700"] });
const notoKn = Noto_Sans_Kannada({ variable: "--font-noto-kn", subsets: ["kannada"], weight: ["400", "600"] });
const notoHi = Noto_Sans_Devanagari({ variable: "--font-noto-hi", subsets: ["devanagari"], weight: ["400", "600"] });

export const metadata: Metadata = {
  title: "NyayaSetu",
  description: "Decision support for legal-aid lawyers working with undertrial prisoners. Not legal advice.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${noto.variable} ${notoKn.variable} ${notoHi.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
