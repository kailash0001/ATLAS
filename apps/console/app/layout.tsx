import type { Metadata } from "next";
import "./styles.css";
export const metadata: Metadata = {
  title: "ATLAS · Control plane",
  description: "Local ML reliability and operations",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
