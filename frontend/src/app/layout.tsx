import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lattice",
  description: "Learn any topic in depth — curiosity, connection, and recall",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
