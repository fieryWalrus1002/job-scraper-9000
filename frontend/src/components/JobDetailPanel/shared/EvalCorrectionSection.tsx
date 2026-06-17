import { useEffect, useState } from 'react'
import type { EvalCorrectionOut } from '../../../types'
import { useDeleteEvalCorrection, useSetEvalCorrection } from '../../../hooks/useEvalCorrection'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { sectionLabel } from './variants'
import { MutationError } from './MutationError'

export function EvalCorrectionSection({
  dedupHash,
  existing,
}: {
  dedupHash: string
  existing: EvalCorrectionOut | null | undefined
}) {
  const upsert = useSetEvalCorrection()
  const del = useDeleteEvalCorrection()
  const [correctedScore, setCorrectedScore] = useState<number | null>(
    existing?.corrected_score ?? null,
  )
  const [reason, setReason] = useState(existing?.correction_reason ?? '')
  const isPending = upsert.isPending || del.isPending

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCorrectedScore(existing?.corrected_score ?? null)
    setReason(existing?.correction_reason ?? '')
  }, [existing?.corrected_score, existing?.correction_reason, dedupHash])

  function handleSave() {
    if (correctedScore == null) return
    upsert.mutate({
      dedup_hash: dedupHash,
      corrected_score: correctedScore,
      correction_reason: reason.trim() || null,
    })
  }

  function handleClear() {
    if (existing) del.mutate(dedupHash)
    setCorrectedScore(null)
    setReason('')
  }

  const trimmedReason = reason.trim()
  const existingReason = (existing?.correction_reason ?? '').trim()
  const isDirty =
    correctedScore !== (existing?.corrected_score ?? null) || trimmedReason !== existingReason
  const canSave = correctedScore != null && (isDirty || !existing)

  function chipCls(n: number, active: boolean) {
    const variant = n >= 4 ? 'high' : n === 3 ? 'mid' : 'low'
    if (!active) {
      return 'bg-card text-muted border-border hover:border-border-strong hover:text-fg'
    }
    return variant === 'high'
      ? 'bg-score-high/20 text-score-high border-score-high/40 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'
      : variant === 'mid'
        ? 'bg-score-mid/20 text-score-mid border-score-mid/40 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'
        : 'bg-score-low/20 text-score-low border-score-low/40 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className={sectionLabel}>Corrected score</div>
        <div className="flex flex-wrap gap-1.5">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              disabled={isPending}
              onClick={() => setCorrectedScore(n)}
              className={cn(
                'size-9 inline-flex items-center justify-center rounded-md border text-[14px] font-mono font-semibold cursor-pointer transition-all tabular-nums disabled:opacity-40 disabled:cursor-default',
                chipCls(n, correctedScore === n),
              )}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className={sectionLabel}>Reason (optional)</div>
        <textarea
          className="w-full min-h-[80px] resize-y bg-bg border border-border rounded-md text-fg text-[13px] leading-[1.55] px-3 py-2 outline-none placeholder:text-faint hover:border-border-strong focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 transition-[color,border-color,box-shadow]"
          value={reason}
          placeholder="What did the AI get wrong?"
          onChange={(e) => setReason(e.target.value)}
        />
      </div>

      <MutationError error={upsert.error ?? del.error} />

      <div className="flex items-center gap-3 pt-3 border-t border-border/60 -mx-0">
        {existing && (
          <div className="text-[11px] text-muted">
            <span className="font-mono">{existing.original_score ?? '—'}</span>
            <span className="text-faint mx-1">→</span>
            <span className="font-mono text-fg">{existing.corrected_score}</span>
            <span className="text-faint ml-2">
              · {new Date(existing.corrected_at).toLocaleDateString()}
            </span>
          </div>
        )}
        <div className="flex gap-2 ml-auto">
          {existing && (
            <Button variant="ghost" size="sm" disabled={isPending} onClick={handleClear}>
              Clear
            </Button>
          )}
          <Button size="sm" disabled={!canSave || isPending} onClick={handleSave}>
            {upsert.isPending ? 'Saving…' : existing ? 'Update' : 'Save'}
          </Button>
        </div>
      </div>
    </div>
  )
}
