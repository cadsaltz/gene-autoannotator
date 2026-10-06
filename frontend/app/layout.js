import { Inter, Roboto_Mono } from "next/font/google";

import { SessionProvider } from "../components/SessionProvider";
import { getServerSession, toClientSession } from "../lib/session";
import { THEME_INIT_SCRIPT } from "../lib/theme";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const robotoMono = Roboto_Mono({
  variable: "--font-roboto-mono",
  subsets: ["latin"],
});

export const metadata = {
  title: "Gene Autoannotator",
  description: "Web UI for queued gene annotation jobs and generated annotation history",
};

export default async function RootLayout({ children }) {
  const session = toClientSession(await getServerSession());
  return (
    <html
      lang="en"
      className={`${inter.variable} ${robotoMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">
        <SessionProvider session={session}>{children}</SessionProvider>
      </body>
    </html>
  );
}
