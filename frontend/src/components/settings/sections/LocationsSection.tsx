import { Input } from '@/components/ui/input'
import { Checkbox, Section } from '../fields'
import { labelCls } from '../formKit'
import type { LocRow, SearchFormState, SetField } from '../searchFormState'

export function LocationsSection({ form, set }: { form: SearchFormState; set: SetField }) {
  return (
    <Section title="Locations">
      <LocationListEditor
        label="Acceptable locations"
        rows={form.acceptable_locations}
        onChange={(rows) => set('acceptable_locations', rows)}
      />
      <LocationListEditor
        label="Excluded locations"
        rows={form.excluded_locations}
        onChange={(rows) => set('excluded_locations', rows)}
      />
      <Checkbox
        label="Willing to relocate"
        checked={form.relocation_willing}
        onChange={(v) => set('relocation_willing', v)}
      />
    </Section>
  )
}

function LocationListEditor({
  label,
  rows,
  onChange,
}: {
  label: string
  rows: LocRow[]
  onChange: (rows: LocRow[]) => void
}) {
  function update(i: number, patch: Partial<LocRow>) {
    onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  }
  function remove(i: number) {
    onChange(rows.filter((_, idx) => idx !== i))
  }
  function add() {
    onChange([...rows, { city: '', region: '', country: 'US' }])
  }

  return (
    <div className="flex flex-col gap-1.5">
      <label className={labelCls}>{label}</label>
      <div className="flex flex-col gap-2">
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_80px_auto] gap-2 items-center">
            <Input
              placeholder="City"
              value={r.city}
              onChange={(e) => update(i, { city: e.target.value })}
            />
            <Input
              placeholder="Region"
              value={r.region}
              onChange={(e) => update(i, { region: e.target.value })}
            />
            <Input
              placeholder="Country"
              value={r.country}
              onChange={(e) => update(i, { country: e.target.value })}
            />
            <button
              type="button"
              className="text-faint hover:text-score-low text-[16px] leading-none px-1.5"
              onClick={() => remove(i)}
              aria-label="Remove location"
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          className="self-start text-[12px] text-primary-hov hover:text-primary"
          onClick={add}
        >
          + Add location
        </button>
      </div>
    </div>
  )
}
