import type { Metadata } from 'next'
import { Space_Mono, DM_Sans } from 'next/font/google'
import './globals.css'

const spaceMono = Space_Mono({
  weight: ['400', '700'],
  subsets: ['latin'],
  variable: '--font-mono',
})

const dmSans = DM_Sans({
  subsets: ['latin'],
  variable: '--font-sans',
})

export const metadata: Metadata = {
  title: 'VN Stock Scanner',
  description: 'Quét VN-Index tự động — lọc, chấm điểm, phân tích',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" className={`${spaceMono.variable} ${dmSans.variable}`}>
      <body>{children}</body>
    </html>
  )
}
