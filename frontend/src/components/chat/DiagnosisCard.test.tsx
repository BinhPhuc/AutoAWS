import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { DiagnosisAnswer } from '@/api/types'
import { DiagnosisCard } from './DiagnosisCard'

const answer: DiagnosisAnswer = {
  summary: 'Tên miền trỏ IP cũ và Security Group chưa mở 8080.',
  root_causes: [
    {
      statement: 'Bản ghi A của app.example.com trỏ về IP cũ 13.212.10.20.',
      confidence: 'high',
      evidence: [
        {
          text: 'Route 53 trả 13.212.10.20',
          source: 'route53_list_records',
          resource_id: 'app.example.com',
          value: '13.212.10.20',
          verified: true,
          verification: 'read',
        },
        {
          text: 'Có thể instance đã stop/start',
          source: 'describe_instances',
          verified: false,
          verification: 'inferred',
        },
      ],
    },
    {
      statement: 'Security Group sg-0d4e chưa mở inbound TCP/8080.',
      confidence: 'medium',
      evidence: [
        {
          text: 'Không thấy luật 8080',
          source: 'describe_security_groups',
          resource_id: 'sg-0bogus',
          verified: false,
          verification: 'not_found',
        },
      ],
    },
  ],
  fix_steps: ['Gắn Elastic IP', 'Mở TCP/8080'],
  unverified: [{ text: 'Container có chạy không', how_to_check: 'docker ps' }],
  confidence: 'high',
  limit_reached: 'time',
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('DiagnosisCard', () => {
  it('renders every root cause with its evidence and the server checks', () => {
    render(wrap(<DiagnosisCard answer={answer} />))
    expect(screen.getByText('Root causes (2)')).toBeInTheDocument()
    expect(screen.getAllByTestId('root-cause')).toHaveLength(2)
    expect(screen.getByText('How to fix')).toBeInTheDocument()
    expect(screen.getByText('Not verified')).toBeInTheDocument()
    expect(screen.getByText('Verified from AWS')).toBeInTheDocument()
    expect(screen.getByText('Inferred')).toBeInTheDocument()
    expect(screen.getByText('Not found in data read')).toBeInTheDocument()
    expect(screen.getByText('app.example.com = 13.212.10.20')).toBeInTheDocument()
    expect(screen.getByText('Check manually')).toBeInTheDocument()
    expect(screen.getAllByText('High confidence')).toHaveLength(2) // overall + first cause
    expect(screen.getByText('Medium confidence')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('time limit')
    // Vietnamese content is rendered as-is
    expect(
      screen.getByText('Tên miền trỏ IP cũ và Security Group chưa mở 8080.'),
    ).toBeInTheDocument()
  })

  it('handles an answer without root causes', () => {
    render(wrap(<DiagnosisCard answer={{ ...answer, root_causes: [], limit_reached: null }} />))
    expect(screen.getByText('Root cause')).toBeInTheDocument()
    expect(screen.getByText(/No misconfiguration found/)).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
