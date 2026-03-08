import type { Metadata } from 'next';
import './globals.css';

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
    <html lang="vi">
      <body className="antialiased">{children}</body>
    </html>
  );
}
