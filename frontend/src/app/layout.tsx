import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'AAIP - Agent Reliability & Performance Protocol',
  description: 'Verify AI agent reliability through multi-judge evaluation',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
