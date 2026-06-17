import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { isQuitKey } from '@/lib/keyboard'

interface Shortcut {
  /** Key chips shown on the right; multiple keys read as alternatives ("or"). */
  keys: string[]
  label: string
}

interface ShortcutGroup {
  title: string
  note?: string
  shortcuts: Shortcut[]
}

// The single source of truth for the reference. Keep in step with useTriageKeys
// (feed), JobDetailShell (scroll) and the surface action shortcuts (detail).
const GROUPS: ShortcutGroup[] = [
  {
    title: 'Jobs feed',
    shortcuts: [
      { keys: ['j', '↓'], label: 'Move cursor down' },
      { keys: ['k', '↑'], label: 'Move cursor up' },
      { keys: ['t'], label: 'Trash' },
      { keys: ['s'], label: 'Shortlist' },
      { keys: ['Enter'], label: 'Open job detail' },
    ],
  },
  {
    title: 'Job detail',
    note: 'Triage keys depend on the tab the job is in; each closes the panel.',
    shortcuts: [
      { keys: ['j', 'k'], label: 'Scroll description' },
      { keys: ['t'], label: 'Trash' },
      { keys: ['s'], label: 'Shortlist' },
      { keys: ['p'], label: 'Pursue (Shortlist → Tracking)' },
      { keys: ['b'], label: 'Back (Shortlist → Jobs / Tracking → Shortlist)' },
      { keys: ['r'], label: 'Restore (Trash → Jobs)' },
      { keys: ['q', 'Esc'], label: 'Close panel' },
    ],
  },
  {
    title: 'Anywhere',
    shortcuts: [{ keys: ['?'], label: 'Show this reference' }],
  },
]

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-border bg-bg-elevated px-1.5 font-mono text-[11px] text-muted">
      {children}
    </kbd>
  )
}

export function ShortcutsOverlay({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-shortcuts-overlay
        className="sm:max-w-[480px] p-0 gap-0 overflow-hidden"
        onKeyDown={(e) => {
          if (isQuitKey(e)) {
            e.preventDefault()
            onOpenChange(false)
          }
        }}
      >
        <div className="px-5 py-4 border-b border-border">
          <DialogTitle className="text-[15px] font-semibold text-fg">
            Keyboard shortcuts
          </DialogTitle>
          <DialogDescription className="text-xs text-muted mt-0.5">
            Single-key triage across the funnel.
          </DialogDescription>
        </div>
        <div className="px-5 py-4 space-y-5 max-h-[70vh] overflow-y-auto">
          {GROUPS.map((group) => (
            <section key={group.title}>
              <h3 className="text-[10px] font-semibold uppercase tracking-[0.08em] text-faint mb-2">
                {group.title}
              </h3>
              {group.note && <p className="text-[11px] text-muted mb-2">{group.note}</p>}
              <dl className="space-y-1.5">
                {group.shortcuts.map((s) => (
                  <div key={s.label} className="flex items-center justify-between gap-3">
                    <dt className="text-[13px] text-fg">{s.label}</dt>
                    <dd className="flex items-center gap-1 shrink-0">
                      {s.keys.map((k, i) => (
                        <span key={k} className="flex items-center gap-1">
                          {i > 0 && <span className="text-[10px] text-faint">or</span>}
                          <Kbd>{k}</Kbd>
                        </span>
                      ))}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
