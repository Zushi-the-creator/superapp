import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NASDAQ Super App - AI-Powered Stock Scanner",
  description: "Real-time stock scanning with technical analysis and AI sentiment",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
