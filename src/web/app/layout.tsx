import type { Metadata } from "next";
import { Plus_Jakarta_Sans, DM_Mono } from "next/font/google";
import { QueryProvider } from "@/lib/react-query";
import { NetworkStatusProvider } from "@/components/providers/NetworkStatusProvider";
import "./globals.css";

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-jakarta",
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
});

const dmMono = DM_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "mingai",
  description: "Enterprise RAG Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <body
        className={`${jakarta.variable} ${dmMono.variable} font-sans antialiased`}
      >
        <QueryProvider>
          <NetworkStatusProvider>{children}</NetworkStatusProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
