import { useState } from 'react'
import { Check, MessageSquareReply, ShieldAlert, Undo2, X } from 'lucide-react'
import type { Proposal, ProposalRef } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { StatusTag } from '@/components/ui/status-tag'
import { Mono } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { useDecide, useProposal, useProposals } from '@/hooks/useProposals'
import { formatTime } from '@/lib/format'
import { S } from '@/lib/strings'
import { ProposalOutcome, ProposalPreview, ProposalStatusTag } from './ProposalParts'

/** "Proposed fixes" block of a diagnosis: one card per proposal the agent made. */
export function ProposalList({
  refs,
  onFollowup,
}: {
  refs: ProposalRef[]
  /** Called with the server's follow-up question after a feedback decision. */
  onFollowup?: (question: string) => void
}) {
  return (
    <div className="space-y-3">
      {refs.map((ref, i) =>
        ref.proposal_id ? (
          <ProposalCard key={ref.proposal_id} id={ref.proposal_id} onFollowup={onFollowup} />
        ) : (
          <div
            key={i}
            className="flex flex-wrap items-start gap-2 rounded-md border border-dashed px-3 py-2"
          >
            <StatusTag tone="neutral">{S.remediation.notProposed}</StatusTag>
            <Mono>{ref.action}</Mono>
            <span className="text-muted-foreground">{ref.error}</span>
          </div>
        ),
      )}
    </div>
  )
}

export function ProposalCard({
  id,
  onFollowup,
}: {
  id: string
  onFollowup?: (question: string) => void
}) {
  const { data: p } = useProposal(id)
  const conversationProposals = useProposals(p?.conversation_id)
  const rollbacks = (conversationProposals.data ?? []).filter(
    (x) => x.parent_id === id && x.kind === 'rollback',
  )
  if (!p) return null
  return (
    <div className="space-y-3">
      <ProposalBody proposal={p} onFollowup={onFollowup} />
      {rollbacks.map((r) => (
        <div key={r.id} className="border-l-2 border-warning-border pl-3">
          <ProposalBody proposal={r} onFollowup={onFollowup} />
        </div>
      ))}
    </div>
  )
}

function ProposalBody({
  proposal: p,
  onFollowup,
}: {
  proposal: Proposal
  onFollowup?: (question: string) => void
}) {
  const t = S.remediation
  const decide = useDecide()
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [feedback, setFeedback] = useState('')
  const pending = p.status === 'PENDING_APPROVAL'

  const send = (decision: 'approve' | 'reject' | 'feedback') =>
    decide.mutate(
      { id: p.id, decision, feedback: decision === 'feedback' ? feedback : '' },
      {
        onSuccess: ({ data }) => {
          setFeedbackOpen(false)
          setFeedback('')
          if (data.followup_question) onFollowup?.(data.followup_question)
        },
      },
    )

  return (
    <section
      data-testid="proposal"
      aria-label={p.preview.summary}
      className="rounded-md border bg-card"
    >
      <header className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
        {p.kind === 'rollback' ? (
          <Undo2 className="size-4 text-warning" aria-hidden />
        ) : (
          <ShieldAlert className="size-4 text-primary" aria-hidden />
        )}
        <h4 className="min-w-0 flex-1 text-sm font-semibold">
          {p.kind === 'rollback' && <span className="text-warning">{t.rollback}: </span>}
          {p.preview.summary}
        </h4>
        <ProposalStatusTag status={p.status} />
      </header>
      <div className="space-y-3 p-3">
        {p.reason && <p className="text-muted-foreground">{p.reason}</p>}
        <ProposalPreview proposal={p} />
        {!pending && p.status !== 'APPROVED' && <ProposalOutcome proposal={p} />}
      </div>
      {pending && (
        <footer className="flex flex-wrap items-center gap-2 border-t bg-muted/40 px-3 py-2">
          <Button size="sm" onClick={() => send('approve')} disabled={decide.isPending}>
            <Check />
            {t.approve}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => send('reject')}
            disabled={decide.isPending}
          >
            <X />
            {t.reject}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setFeedbackOpen(true)}
            disabled={decide.isPending}
          >
            <MessageSquareReply />
            {t.feedback}
          </Button>
          {p.expires_at && (
            <span className="tabular ml-auto text-xs text-muted-foreground">
              {t.expires} {formatTime(p.expires_at)}
            </span>
          )}
        </footer>
      )}

      <Dialog open={feedbackOpen} onOpenChange={setFeedbackOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.feedbackTitle}</DialogTitle>
            <DialogDescription>{t.feedbackHint}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor={`fb-${p.id}`}>{t.feedback}</Label>
            <Textarea
              id={`fb-${p.id}`}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder={t.feedbackPlaceholder}
              rows={3}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFeedbackOpen(false)}>
              {S.common.cancel}
            </Button>
            <Button
              onClick={() => send('feedback')}
              disabled={!feedback.trim() || decide.isPending}
            >
              {t.send}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
