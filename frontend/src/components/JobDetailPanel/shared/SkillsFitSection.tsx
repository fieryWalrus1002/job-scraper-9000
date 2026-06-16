import type { AiFitDetail } from '../../../types'
import { cn } from '@/lib/utils'
import { sectionLabel } from './variants'

function BulletList({
  items,
  markerClass,
  itemClass,
}: {
  items: unknown
  markerClass?: string
  itemClass?: string
}) {
  const arr = Array.isArray(items) ? items.filter((v): v is string => typeof v === 'string') : []
  if (arr.length === 0) return <span className="text-faint text-[13px]">None</span>
  return (
    <ul className={cn('m-0 pl-4 flex flex-col gap-1.5', markerClass, itemClass)}>
      {arr.map((item, i) => (
        <li key={`${i}-${item}`} className="text-[13px] leading-[1.6] text-fg marker:text-faint">
          {item}
        </li>
      ))}
    </ul>
  )
}

export function SkillsFitSection({ ai }: { ai: AiFitDetail | null }) {
  if (!ai) return <p className="text-faint text-[13px]">No skills fit data available.</p>
  return (
    <div className="flex flex-col gap-4">
      {ai.score_rationale && (
        <div className="flex flex-col gap-1.5">
          <div className={sectionLabel}>Rationale</div>
          <div className="text-[13px] leading-[1.65] text-fg bg-bg border border-border rounded-md px-4 py-3 whitespace-pre-wrap shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]">
            {ai.score_rationale}
          </div>
        </div>
      )}
      {!!ai.core_job_duties?.length && (
        <div className="flex flex-col gap-1.5">
          <div className={sectionLabel}>Core Duties</div>
          <BulletList items={ai.core_job_duties} />
        </div>
      )}
      {!!ai.top_matches?.length && (
        <div className="flex flex-col gap-1.5">
          <div className={cn(sectionLabel, 'text-score-high/80')}>Matches</div>
          <BulletList items={ai.top_matches} markerClass="[&_li]:marker:text-score-high" />
        </div>
      )}
      {!!ai.gaps?.length && (
        <div className="flex flex-col gap-1.5">
          <div className={cn(sectionLabel, 'text-score-mid/80')}>Gaps</div>
          <BulletList items={ai.gaps} markerClass="[&_li]:marker:text-score-mid" />
        </div>
      )}
      {!!ai.hard_concerns?.length && (
        <div className="flex flex-col gap-1.5">
          <div className={cn(sectionLabel, 'text-score-low/80')}>Hard Concerns</div>
          <BulletList
            items={ai.hard_concerns}
            markerClass="[&_li]:marker:text-score-low [&_li]:text-score-low/90"
          />
        </div>
      )}
    </div>
  )
}
