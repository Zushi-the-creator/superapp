import type { Metadata } from "next";
import "./globals.css";
import { DataProvider } from "@/components/providers/DataProvider";

export const metadata: Metadata = {
  title: "ATLAS V2 - Trading Dashboard",
  description: "Live portfolio tracking with ML-powered signals",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <DataProvider>{children}</DataProvider>
      </body>
    </html>
  );
}
