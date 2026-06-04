import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'

export interface ContextMenuItem {
  label: string
  active?: boolean
  onClick: () => void
}

interface Props {
  x: number
  y: number
  items: ContextMenuItem[]
  onClose: () => void
}

export default function ContextMenu({ x, y, items, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', handleDown)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleDown)
      document.removeEventListener('keydown', handleKey)
    }
  }, [onClose])

  const style: React.CSSProperties = {
    position: 'fixed',
    top: Math.min(y, window.innerHeight - 200),
    left: Math.min(x, window.innerWidth - 180),
  }

  return (
    <div
      ref={ref}
      className="z-[1000] bg-card border border-border rounded-lg shadow-[0_12px_32px_-4px_rgba(0,0,0,0.6),inset_0_1px_0_rgba(255,255,255,0.04)] min-w-[160px] p-1 flex flex-col backdrop-blur-md"
      style={style}
    >
      {items.map((item) => (
        <button
          key={item.label}
          className={cn(
            'block w-full text-left py-1.5 px-2.5 text-[13px] bg-transparent border-none rounded-md text-fg cursor-pointer hover:bg-hover transition-colors flex items-center justify-between gap-2',
            item.active && 'text-primary-hov font-medium bg-primary/10',
          )}
          onClick={() => { item.onClick(); onClose() }}
        >
          <span>{item.label}</span>
          {item.active && (
            <svg width="12" height="12" viewBox="0 0 12 12" className="text-primary-hov shrink-0">
              <path d="M2.5 6 L5 8.5 L9.5 3.5" stroke="currentColor" strokeWidth="1.75" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </button>
      ))}
    </div>
  )
}
