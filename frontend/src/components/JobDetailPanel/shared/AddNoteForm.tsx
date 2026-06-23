import { useState } from 'react'
import { useCreateEvent } from '@/hooks/useApplications'
import { EVENT_TAG_SUGGESTIONS } from '@/lib/eventTags'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface Props {
  dedupHash: string
  onSuccess: () => void
}

const labelCls = 'text-[10px] font-semibold text-muted uppercase tracking-[0.08em]'
const textareaCls =
  'w-full min-h-[70px] resize-y bg-bg-elevated border border-border rounded-md text-fg text-[13px] leading-[1.55] px-2.5 py-2 outline-none ' +
  'placeholder:text-faint hover:border-border-strong ' +
  'focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 ' +
  'transition-[color,border-color,box-shadow]'

export function AddNoteForm({ dedupHash, onSuccess }: Props) {
  const [date, setDate] = useState(todayLocalISO())
  const [body, setBody] = useState('')
  const [tagInput, setTagInput] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [apiError, setApiError] = useState<string | null>(null)

  const mutation = useCreateEvent()

  function addTag(value: string) {
    const trimmed = value.trim().toLowerCase()
    if (!trimmed || tags.includes(trimmed)) return
    setTags((prev) => [...prev, trimmed])
  }

  function removeTag(tag: string) {
    setTags((prev) => prev.filter((t) => t !== tag))
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setApiError(null)
    try {
      await mutation.mutateAsync({
        dedupHash,
        body: {
          kind: 'event' as const,
          occurred_at: date || undefined,
          body: body.trim() || null,
          tags: tags.length > 0 ? tags : undefined,
        },
      })
      // Reset form
      setDate(todayLocalISO())
      setBody('')
      setTagInput('')
      setTags([])
      setApiError(null)
      onSuccess()
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setApiError(msg)
    }
  }

  function handleTagKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      addTag(tagInput)
      setTagInput('')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <label className={labelCls} htmlFor="note-date">
          Date
        </label>
        <Input id="note-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </div>

      <div className="flex flex-col gap-1.5">
        <label className={labelCls} htmlFor="note-tags">
          Tags
        </label>
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-1">
            {tags.map((tag) => (
              <Badge
                key={tag}
                variant="secondary"
                className="text-[10px] cursor-pointer hover:bg-muted"
                onClick={() => removeTag(tag)}
                title={`Click to remove "${tag}"`}
              >
                {tag} ×
              </Badge>
            ))}
          </div>
          <div className="flex gap-2">
            <Input
              id="note-tags"
              placeholder="Type tag + Enter"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={handleTagKeyDown}
              className="flex-1"
            />
          </div>
          {EVENT_TAG_SUGGESTIONS.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {EVENT_TAG_SUGGESTIONS.filter((s) => !tags.includes(s)).map((suggestion) => (
                <Badge
                  key={suggestion}
                  variant="outline"
                  className="text-[10px] cursor-pointer hover:bg-muted border-dashed"
                  onClick={() => {
                    addTag(suggestion)
                  }}
                >
                  + {suggestion}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <label className={labelCls} htmlFor="note-body">
          Note
        </label>
        <textarea
          id="note-body"
          className={textareaCls}
          placeholder="What happened?"
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
      </div>

      {apiError && (
        <div className="text-[12px] text-score-low bg-score-low/10 border border-score-low/20 rounded-md px-3 py-2">
          {apiError}
        </div>
      )}

      <div className="flex justify-end gap-3">
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving…' : 'Add note'}
        </Button>
      </div>
    </form>
  )
}

function todayLocalISO(): string {
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}
