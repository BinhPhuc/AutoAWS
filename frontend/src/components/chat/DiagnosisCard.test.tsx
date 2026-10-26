import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { DiagnosisAnswer } from '@/api/types'
import { DiagnosisCard } from './DiagnosisCard'

const answer: DiagnosisAnswer = {
  summary: 'Subnet không có đường ra Internet.',
  cause: 'Route table rtb-07c9 không có tuyến 0.0.0.0/0.',
  evidence: [
    { text: 'rtb-07c9 chỉ có tuyến local', source: 'describe_route_tables', verified: true },
    { text: 'Có thể do deploy gần đây', source: 'describe_instances', verified: false },
  ],
  fix_steps: ['Thêm tuyến 0.0.0.0/0 → igw'],
  unverified: [{ text: 'sshd có chạy không', how_to_check: 'systemctl status sshd' }],
  confidence: 'high',
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('DiagnosisCard', () => {
  it('renders the four sections with badges', () => {
    render(wrap(<DiagnosisCard answer={answer} />))
    expect(screen.getByText('Root cause')).toBeInTheDocument()
    expect(screen.getByText('Evidence')).toBeInTheDocument()
    expect(screen.getByText('How to fix')).toBeInTheDocument()
    expect(screen.getByText('Not verified')).toBeInTheDocument()
    expect(screen.getByText('Verified from AWS')).toBeInTheDocument()
    expect(screen.getByText('Inferred')).toBeInTheDocument()
    expect(screen.getByText('Check manually')).toBeInTheDocument()
    expect(screen.getByText('High confidence')).toBeInTheDocument()
    expect(screen.getByText('systemctl status sshd')).toBeInTheDocument()
    // Vietnamese content is rendered as-is
    expect(screen.getByText('Subnet không có đường ra Internet.')).toBeInTheDocument()
  })
})
