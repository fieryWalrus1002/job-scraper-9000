// Non-component shared bits for the settings forms (kept out of fields.tsx so
// that file can export only components — react-refresh requires it).

export const labelCls = 'text-[10px] font-semibold text-muted uppercase tracking-[0.08em]'
export const textareaCls =
  'w-full resize-y bg-bg-elevated border border-border rounded-md text-fg text-[13px] leading-[1.55] px-2.5 py-2 outline-none ' +
  'placeholder:text-faint hover:border-border-strong ' +
  'focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 ' +
  'transition-[color,border-color,box-shadow]'

// List fields edit as newline-separated text (one item per line), mirroring how
// the YAML intake template reads. split/join is lossless apart from blank lines.
export const linesToList = (text: string): string[] =>
  text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
export const listToLines = (list: string[] | undefined): string => (list ?? []).join('\n')
