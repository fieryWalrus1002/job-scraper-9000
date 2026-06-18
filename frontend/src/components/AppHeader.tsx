import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { Button } from './ui/button'
import { cn } from '../lib/utils'
import { useUnsavedGuard } from './UnsavedGuard'

export type FunnelPath = '/trash' | '/jobs' | '/shortlist' | '/tracking'

const FUNNEL_TABS: { path: FunnelPath; label: string; muted?: boolean }[] = [
  { path: '/trash', label: 'Trash', muted: true },
  { path: '/jobs', label: 'Jobs' },
  { path: '/shortlist', label: 'Shortlist' },
  { path: '/tracking', label: 'Tracking' },
]

const tabBtn =
  'group relative inline-flex items-center gap-2 h-8 px-3 border-none bg-transparent text-muted text-[13px] font-medium cursor-pointer rounded-md transition-all hover:text-fg hover:bg-hover/50 no-underline'
const tabBtnActive =
  'text-fg bg-card border border-border shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]'
const tabBtnMuted = 'text-faint hover:text-muted'
const tabCount =
  'inline-flex items-center justify-center min-w-[20px] h-[18px] px-1.5 rounded text-[10.5px] font-mono tabular-nums font-medium ' +
  'bg-bg-elevated/80 text-faint border border-border/60 ' +
  'group-hover:text-muted group-hover:border-border transition-colors'
const tabCountActive = 'text-primary-hov bg-primary/15 border-primary/30'

interface Props {
  email: string
  /** Badge count per funnel tab; undefined hides the badge (e.g. jobs total still loading). */
  counts: Record<FunnelPath, number | undefined>
  onAddJob: () => void
  onShowShortcuts: () => void
}

export function AppHeader({ email, counts, onAddJob, onShowShortcuts }: Props) {
  const location = useLocation()
  const navigate = useNavigate()
  const { requestNavigation } = useUnsavedGuard()
  const onSettings = location.pathname === '/settings'

  return (
    <header className="flex items-center gap-6 px-5 h-[52px] border-b border-border shrink-0 bg-card/60 backdrop-blur-md">
      <div className="flex items-center gap-2.5">
        <div className="size-6 rounded-md bg-gradient-to-br from-primary to-primary-dim flex items-center justify-center shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_1px_4px_rgba(99,102,241,0.4)]">
          <span className="text-[11px] font-bold text-white tracking-tight">JS</span>
        </div>
        <span className="font-semibold text-[14px] text-fg whitespace-nowrap tracking-tight">
          Job Scraper <span className="text-muted font-normal">9000</span>
        </span>
      </div>
      <nav className="flex items-center gap-1.5" aria-label="Triage funnel">
        {FUNNEL_TABS.map((tab) => {
          const count = counts[tab.path]
          const to = { pathname: tab.path, search: tab.path === '/jobs' ? location.search : '' }
          return (
            <NavLink
              key={tab.path}
              to={to}
              onClick={(e) => {
                // Let modifier-clicks open a new tab; intercept plain clicks so
                // the unsaved-edits guard can confirm before we leave the page.
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
                e.preventDefault()
                requestNavigation(() => navigate(to))
              }}
              className={({ isActive }) =>
                cn(tabBtn, tab.muted && tabBtnMuted, isActive && tabBtnActive)
              }
            >
              {({ isActive }) => (
                <>
                  <span>{tab.label}</span>
                  {count != null && (count > 0 || tab.path !== '/trash') && (
                    <span className={cn(tabCount, isActive && tabCountActive)}>
                      {count.toLocaleString()}
                    </span>
                  )}
                </>
              )}
            </NavLink>
          )
        })}
      </nav>
      <div className="flex-1" />
      <button
        type="button"
        onClick={onShowShortcuts}
        title="Keyboard shortcuts (?)"
        aria-label="Keyboard shortcuts"
        className="inline-flex items-center justify-center size-6 rounded-md border border-border bg-card text-faint text-[12px] font-mono cursor-pointer hover:text-fg hover:border-border-strong transition-colors"
      >
        ?
      </button>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => navigate('/settings')}
        className={cn('text-[12px]', onSettings && 'text-fg')}
      >
        Settings
      </Button>
      <a
        href="/.auth/logout"
        className="text-[12px] text-muted hover:text-fg transition-colors"
        title="Sign out"
      >
        {email}
      </a>
      <Button onClick={onAddJob}>
        <span className="text-[15px] leading-none mr-0.5">+</span>
        Add job
      </Button>
    </header>
  )
}
