import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** Short context for the fallback heading, e.g. "Jobs" or "Settings". */
  label?: string
  /**
   * When any value in this array changes, the boundary resets and re-renders
   * its children. Pass the current route path so navigating away from a crashed
   * route recovers instead of staying stuck on the fallback.
   */
  resetKeys?: unknown[]
  /** Override the default fallback UI. */
  fallback?: (error: Error, reset: () => void) => ReactNode
}

interface State {
  error: Error | null
}

/**
 * Catches render errors in its subtree so one crashing component can't
 * white-screen the whole app. Fails loudly: the error is logged and shown,
 * never silently swallowed.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught a render error', error, info.componentStack)
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && !shallowEqual(prev.resetKeys, this.props.resetKeys)) {
      this.reset()
    }
  }

  reset = () => this.setState({ error: null })

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    if (this.props.fallback) return this.props.fallback(error, this.reset)

    return (
      <div
        role="alert"
        data-testid="error-boundary-fallback"
        className="flex flex-col items-center justify-center gap-3 py-20 text-center"
      >
        <div className="text-sm text-fg">
          Something went wrong{this.props.label ? ` in ${this.props.label}` : ''}.
        </div>
        <div className="max-w-md text-xs text-faint break-words">{error.message}</div>
        <div className="flex gap-2">
          <button
            onClick={this.reset}
            className="text-xs px-3 h-7 rounded-md border border-border bg-card text-muted hover:text-fg hover:border-border-strong transition-colors"
          >
            Try again
          </button>
          <button
            onClick={() => window.location.reload()}
            className="text-xs px-3 h-7 rounded-md border border-border bg-card text-muted hover:text-fg hover:border-border-strong transition-colors"
          >
            Reload
          </button>
        </div>
      </div>
    )
  }
}

function shallowEqual(a?: unknown[], b?: unknown[]): boolean {
  if (a === b) return true
  if (!a || !b || a.length !== b.length) return false
  return a.every((v, i) => Object.is(v, b[i]))
}
