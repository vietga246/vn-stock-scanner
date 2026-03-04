import type { Metadata } from 'next';
import { Space_Grotesk } from 'next/font/google';
import './globals.css';

const spaceGrotesk = Space_Grotesk({
  subsets: ['latin', 'vietnamese'],
  variable: '--font-space-grotesk',
});

export const metadata: Metadata = {
  title: 'VN Stock Scanner - Market Intelligence',
  description: 'Hệ thống quét và phân tích cổ phiếu Việt Nam với AI',
  keywords: ['stock', 'vietnam', 'vnindex', 'analysis', 'scanner'],
  authors: [{ name: 'VN Stock Scanner' }],
  openGraph: {
    title: 'VN Stock Scanner',
    description: 'Hệ thống quét và phân tích cổ phiếu Việt Nam với AI',
    type: 'website',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi" className={spaceGrotesk.variable}>
      <body className="antialiased">{children}</body>
    </html>
  );
}
