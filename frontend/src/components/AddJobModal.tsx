import { useState } from 'react'
import { useCreateManualJob } from '../hooks/useApplications'
import { APPLICATION_STATUSES, STATUS_LABELS } from '../types'
import type { ApplicationStatus } from '../types'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

interface Props {
  onClose: () => void
  onSuccess: () => void
}

const labelCls = 'text-[10px] font-semibold text-muted uppercase tracking-[0.08em]'
const textareaCls =
  'w-full min-h-[110px] resize-y bg-bg-elevated border border-border rounded-md text-fg text-[13px] leading-[1.55] px-2.5 py-2 outline-none ' +
  'placeholder:text-faint hover:border-border-strong ' +
  'focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 ' +
  'transition-[color,border-color,box-shadow]'

export default function AddJobModal({ onClose, onSuccess }: Props) {
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState('')
  const [url, setUrl] = useState('')
  const [description, setDescription] = useState('')
  const [location, setLocation] = useState('')
  const [postedAt, setPostedAt] = useState('')
  const [fitScore, setFitScore] = useState<number | ''>('')
  const [status, setStatus] = useState<ApplicationStatus>('saved')
  const [apiError, setApiError] = useState<string | null>(null)

  const mutation = useCreateManualJob()

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setApiError(null)
    if (fitScore === '') { setApiError('Score is required.'); return }
    try {
      await mutation.mutateAsync({
        title: title.trim(),
        fit_score: fitScore,
        company: company.trim() || null,
        source_url: url.trim() || null,
        description: description.trim() || null,
        location: location.trim() || null,
        posted_at: postedAt || null,
        status,
      })
      onSuccess()
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setApiError(msg.startsWith('409') ? 'This job is already in the system.' : msg)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[600px] p-0 gap-0">
        <div className="px-6 pt-5 pb-4 border-b border-border">
          <DialogTitle className="text-[15px] font-semibold tracking-tight text-fg">
            Add job manually
          </DialogTitle>
          <p className="text-[12px] text-muted mt-1">
            Track a job that wasn't found by the scraper.
          </p>
        </div>

        <form className="grid grid-cols-2 gap-x-4 gap-y-3.5 px-6 py-5" onSubmit={handleSubmit}>
          <div className="flex flex-col gap-1.5 col-span-2">
            <label className={labelCls}>
              Title <span className="text-score-low normal-case">*</span>
            </label>
            <Input
              required
              placeholder="e.g. Senior Software Engineer"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className={labelCls}>Company</label>
            <Input
              placeholder="e.g. Acme Corp"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className={labelCls}>Location</label>
            <Input
              placeholder="e.g. Remote, Seattle WA"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5 col-span-2">
            <label className={labelCls}>Job URL</label>
            <Input
              type="text"
              placeholder="https://…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5 col-span-2">
            <label className={labelCls}>Job description</label>
            <textarea
              className={textareaCls}
              placeholder="Copy-paste the job description here."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className={labelCls}>Posted date</label>
            <Input
              type="date"
              value={postedAt}
              onChange={(e) => setPostedAt(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className={labelCls}>
              Your fit score <span className="text-score-low normal-case">*</span>
            </label>
            <Select
              value={fitScore === '' ? undefined : String(fitScore)}
              onValueChange={(v) => setFitScore(Number(v))}
            >
              <SelectTrigger className="w-full h-8 text-[13px] bg-bg-elevated border-border hover:border-border-strong">
                <SelectValue placeholder="— pick one —" />
              </SelectTrigger>
              <SelectContent>
                {[1, 2, 3, 4, 5].map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    <span className="font-mono">{n}</span> <span className="text-muted">— {scoreHint(n)}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1.5 col-span-2">
            <label className={labelCls}>Initial status</label>
            <Select value={status} onValueChange={(v) => setStatus(v as ApplicationStatus)}>
              <SelectTrigger className="w-full h-8 text-[13px] bg-bg-elevated border-border hover:border-border-strong">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {APPLICATION_STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {STATUS_LABELS[s]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {apiError && (
            <div className="col-span-2 text-[12px] text-score-low bg-score-low/10 border border-score-low/20 rounded-md px-3 py-2">
              {apiError}
            </div>
          )}

          <div className="col-span-2 flex justify-end gap-2 pt-2 mt-1 border-t border-border -mx-6 px-6 pb-1">
            <Button type="button" variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={mutation.isPending}>
              {mutation.isPending ? 'Adding…' : 'Add job'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function scoreHint(n: number): string {
  switch (n) {
    case 5: return 'Perfect fit'
    case 4: return 'Strong fit'
    case 3: return 'Possible fit'
    case 2: return 'Weak fit'
    case 1: return 'Poor fit'
    default: return ''
  }
}
