import { useState } from 'react'
import { loadColumnVisibility, saveColumnVisibility } from '../lib/columns'

export function useColumnConfig() {
  const [visible, setVisible] = useState<Set<string>>(loadColumnVisibility)

  function toggle(key: string) {
    setVisible((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      saveColumnVisibility(next)
      return next
    })
  }

  return { visible, toggle }
}
