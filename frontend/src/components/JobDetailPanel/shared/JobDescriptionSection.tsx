import rehypeRaw from 'rehype-raw'
import rehypeSanitize from 'rehype-sanitize'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/lib/utils'

const markdownComponents: Components = {
  h1: ({ node, className, ...props }) => {
    void node
    return (
      <h1 {...props} className={cn('mt-0 mb-2 text-xl leading-tight font-semibold', className)} />
    )
  },
  h2: ({ node, className, ...props }) => {
    void node
    return (
      <h2 {...props} className={cn('mt-4 mb-2 text-lg leading-tight font-semibold', className)} />
    )
  },
  h3: ({ node, className, ...props }) => {
    void node
    return (
      <h3 {...props} className={cn('mt-4 mb-2 text-base leading-tight font-semibold', className)} />
    )
  },
  h4: ({ node, className, ...props }) => {
    void node
    return (
      <h4 {...props} className={cn('mt-4 mb-2 text-sm leading-tight font-semibold', className)} />
    )
  },
  p: ({ node, className, ...props }) => {
    void node
    return (
      <p {...props} className={cn('my-3 whitespace-pre-wrap first:mt-0 last:mb-0', className)} />
    )
  },
  ul: ({ node, className, ...props }) => {
    void node
    return <ul {...props} className={cn('my-3 list-disc pl-5 first:mt-0 last:mb-0', className)} />
  },
  ol: ({ node, className, ...props }) => {
    void node
    return (
      <ol {...props} className={cn('my-3 list-decimal pl-5 first:mt-0 last:mb-0', className)} />
    )
  },
  li: ({ node, className, ...props }) => {
    void node
    return <li {...props} className={cn('my-1 pl-0.5 whitespace-pre-wrap', className)} />
  },
  a: ({ node, className, ...props }) => {
    void node
    return (
      <a
        {...props}
        className={cn('text-primary-hov underline underline-offset-2', className)}
        target="_blank"
        rel="noreferrer"
      />
    )
  },
  strong: ({ node, className, ...props }) => {
    void node
    return <strong {...props} className={cn('font-semibold text-fg', className)} />
  },
  blockquote: ({ node, className, ...props }) => {
    void node
    return (
      <blockquote
        {...props}
        className={cn('my-3 border-l-3 border-border-strong pl-3 text-muted', className)}
      />
    )
  },
  code: ({ node, className, ...props }) => {
    void node
    return (
      <code
        {...props}
        className={cn(
          'rounded border border-border bg-bg-elevated px-1 py-0.5 font-mono text-[0.92em]',
          className,
        )}
      />
    )
  },
}

export function JobDescriptionSection({ description }: { description: string | null }) {
  const body = description?.trim()

  return (
    <div className="font-sans text-[13px] leading-[1.7] text-fg break-words m-0 max-h-[420px] overflow-y-auto bg-bg border border-border rounded-md px-4 py-3.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]">
      {body ? (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw, rehypeSanitize]}
          components={markdownComponents}
        >
          {body}
        </ReactMarkdown>
      ) : (
        <span className="text-faint">No description available.</span>
      )}
    </div>
  )
}
