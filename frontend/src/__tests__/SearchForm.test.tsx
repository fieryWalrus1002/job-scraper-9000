import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SearchForm from '../components/settings/SearchForm'
import type { SearchConfigInput } from '../types'

function renderForm(props: React.ComponentProps<typeof SearchForm>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <SearchForm {...props} />
    </QueryClientProvider>,
  )
}

const EXISTING: SearchConfigInput = {
  user: {
    display_name: 'Dev User',
    email: 'dev@example.com',
    home_location: { city: 'Denver', region: 'CO', country: 'US' },
  },
  search_profile: {
    name: 'default search',
    status: 'active',
    goal_summary: 'Find backend platform roles.',
    search_mode: 'balanced',
  },
  roles: {
    target_titles: { preferred: ['Software Engineer', 'Backend Engineer'], exploratory: ['SRE'] },
    excluded_titles: ['Sales Engineer'],
  },
  work_constraints: {
    employment_types: { acceptable: ['fulltime', 'contract'] },
    work_arrangements: {
      remote: { acceptable: true, preferred: true, required: false },
      hybrid: { acceptable: true, preferred: false, required: false },
      onsite: { acceptable: false, preferred: false, required: false },
    },
    max_travel_days: 20,
  },
  locations: {
    acceptable: [{ city: 'Denver', region: 'CO', country: 'US' }],
    preferred: [],
    excluded: [{ city: 'Boston', region: 'MA', country: 'US' }],
    relocation: { willing: true },
  },
  organizations: {
    target_companies: ['Acme'],
    similar_to: ['GitHub'],
    preferred_organization_types: ['product'],
  },
  industries_and_domains: { preferred: ['developer tools'], excluded: ['adtech'] },
  keywords: {
    required_any: ['python'],
    required_all: ['postgres'],
    preferred: ['distributed systems'],
    excluded: ['wordpress'],
  },
  scrape_preferences: {
    include_remote_national_searches: true,
    include_local_searches: true,
    include_company_board_searches: false,
    include_general_job_boards: true,
    max_results_per_task: 75,
    freshness_hours: 24,
    cadence: 'daily',
    salary_floor_k: 80,
    linkedin_experience_codes: ['2', '3', '4', '5'],
  },
}

function stubSearchSave({
  status = 200,
  body = {
    policies: {
      remote: { acceptable_classifications: ['fully_remote'], max_travel_days: 10 },
      prefilter: { excluded_title_terms: ['Sales Engineer'] },
    },
    updated_at: '2026-06-11T00:00:00Z',
  },
}: {
  status?: number
  body?: unknown
} = {}) {
  let sentBody: SearchConfigInput | null = null
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, opts?: RequestInit) => {
      if (url.endsWith('/api/settings/search') && opts?.method === 'PUT') {
        sentBody = JSON.parse(opts.body as string) as SearchConfigInput
        return Promise.resolve(new Response(JSON.stringify(body), { status }))
      }
      return Promise.reject(new Error(`unexpected fetch: ${opts?.method ?? 'GET'} ${url}`))
    }),
  )
  return { getSentBody: () => sentBody }
}

describe('SearchForm', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    // Radix Select asks for pointer-capture APIs that jsdom does not implement.
    Object.defineProperty(HTMLElement.prototype, 'hasPointerCapture', {
      configurable: true,
      value: () => false,
    })
    Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', {
      configurable: true,
      value: () => undefined,
    })
    Object.defineProperty(HTMLElement.prototype, 'releasePointerCapture', {
      configurable: true,
      value: () => undefined,
    })
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: () => undefined,
    })
  })

  it('renders the current search config sections', () => {
    renderForm({ initial: EXISTING, policies: { remote: { acceptable_classifications: [] } } })

    for (const name of [
      'Search targeting',
      'Roles',
      'Work constraints',
      'Locations',
      'Organizations & domains',
      'Keywords',
      'Scrape preferences',
      'Derived policies (read-only)',
    ]) {
      expect(screen.getByRole('heading', { name })).toBeInTheDocument()
    }
  })

  it('shows onboarding state with no config', () => {
    renderForm({ initial: null, policies: null })
    expect(screen.getByText(/No search config yet/i)).toBeInTheDocument()
  })

  it('seeds fields from an existing config', () => {
    renderForm({ initial: EXISTING, policies: null })

    expect(screen.getByDisplayValue('Dev User')).toBeInTheDocument()
    expect(screen.getByDisplayValue('dev@example.com')).toBeInTheDocument()
    expect(screen.getByDisplayValue('default search')).toBeInTheDocument()
    expect(screen.getByDisplayValue(/Software Engineer Backend Engineer/)).toBeInTheDocument()
    expect(screen.getByDisplayValue('Sales Engineer')).toBeInTheDocument()
    expect(screen.getAllByDisplayValue('Denver')).toHaveLength(2)
    expect(screen.getByDisplayValue('Boston')).toBeInTheDocument()
    expect(screen.getByDisplayValue('75')).toBeInTheDocument()
    expect(screen.getByDisplayValue('20')).toBeInTheDocument()
    expect(screen.getByLabelText('fulltime')).toBeChecked()
    expect(screen.getByLabelText('contract')).toBeChecked()
    expect(screen.getByLabelText('parttime')).not.toBeChecked()
    expect(screen.getByLabelText('Entry level')).toBeChecked()
    expect(screen.getByLabelText('Associate')).toBeChecked()
    expect(screen.getByLabelText('Mid-Senior level')).toBeChecked()
    expect(screen.getByLabelText('Director')).toBeChecked()
    expect(screen.getByLabelText('Internship')).not.toBeChecked()
    expect(screen.getByLabelText('Executive')).not.toBeChecked()
    expect(screen.getByLabelText('Willing to relocate')).toBeChecked()
    expect(screen.queryByText(/No search config yet/i)).not.toBeInTheDocument()
  })

  it('submits edited select state as the expected payload', async () => {
    const save = stubSearchSave()
    renderForm({ initial: EXISTING, policies: null })

    const searchModeSelect = screen.getAllByRole('combobox')[0]
    searchModeSelect.focus()
    fireEvent.keyDown(searchModeSelect, { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'focused' }))
    fireEvent.click(screen.getByRole('button', { name: /Save search config/i }))

    await waitFor(() => expect(save.getSentBody()).not.toBeNull())
    expect(save.getSentBody()!.search_profile.search_mode).toBe('focused')
  })

  it('submits edited input, checkbox, and location state as the expected payload', async () => {
    const save = stubSearchSave()
    renderForm({ initial: EXISTING, policies: null })

    fireEvent.change(screen.getByDisplayValue('Dev User'), { target: { value: 'New Dev' } })
    fireEvent.change(screen.getByDisplayValue(/Software Engineer Backend Engineer/), {
      target: { value: 'Platform Engineer\nData Engineer' },
    })
    fireEvent.click(screen.getByLabelText('contract'))
    fireEvent.click(screen.getByLabelText('parttime'))
    fireEvent.click(screen.getByLabelText('Company board searches'))
    fireEvent.change(screen.getByDisplayValue('20'), { target: { value: '10' } })
    fireEvent.click(screen.getByLabelText('Internship'))
    fireEvent.click(screen.getByLabelText('Director'))
    const salaryFloorSelect = screen.getAllByRole('combobox')[2]
    salaryFloorSelect.focus()
    fireEvent.keyDown(salaryFloorSelect, { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: '$120k+' }))
    fireEvent.click(screen.getAllByText('+ Add location')[0])
    await waitFor(() => expect(screen.getAllByPlaceholderText('City')).toHaveLength(3))
    const cityInputs = screen.getAllByPlaceholderText('City')
    const regionInputs = screen.getAllByPlaceholderText('Region')
    fireEvent.change(cityInputs[1], { target: { value: 'Portland' } })
    fireEvent.change(regionInputs[1], { target: { value: 'OR' } })

    fireEvent.click(screen.getByRole('button', { name: /Save search config/i }))

    await waitFor(() => expect(save.getSentBody()).not.toBeNull())
    const sentBody = save.getSentBody()!
    expect(sentBody.user.display_name).toBe('New Dev')
    expect(sentBody.roles.target_titles.preferred).toEqual(['Platform Engineer', 'Data Engineer'])
    expect(sentBody.work_constraints!.employment_types.acceptable).toEqual(['fulltime', 'parttime'])
    expect(sentBody.work_constraints!.max_travel_days).toBe(10)
    expect(sentBody.locations!.acceptable).toEqual([
      { city: 'Denver', region: 'CO', country: 'US' },
      { city: 'Portland', region: 'OR', country: 'US' },
    ])
    expect(sentBody.scrape_preferences!.include_company_board_searches).toBe(true)
    expect(sentBody.scrape_preferences!.salary_floor_k).toBe(120)
    expect(sentBody.scrape_preferences!.linkedin_experience_codes).toEqual(['1', '2', '3', '4'])
    expect(await screen.findByText(/Derived policies/i)).toBeInTheDocument()
    expect(screen.getByText(/excluded_title_terms/)).toBeInTheDocument()
    expect(screen.getByText(/max_travel_days/)).toBeInTheDocument()
  })

  it('removes location rows before submitting', async () => {
    const save = stubSearchSave()
    renderForm({ initial: EXISTING, policies: null })

    fireEvent.click(screen.getAllByLabelText('Remove location')[0])
    fireEvent.click(screen.getByRole('button', { name: /Save search config/i }))

    await waitFor(() => expect(save.getSentBody()).not.toBeNull())
    expect(save.getSentBody()!.locations!.acceptable).toEqual([])
    expect(save.getSentBody()!.locations!.excluded).toEqual([
      { city: 'Boston', region: 'MA', country: 'US' },
    ])
  })

  it('reports dirty on edit and clean again after a successful save', async () => {
    const save = stubSearchSave()
    const onDirtyChange = vi.fn()
    renderForm({ initial: EXISTING, policies: null, onDirtyChange })

    // Seeds clean.
    expect(onDirtyChange).toHaveBeenLastCalledWith(false)

    fireEvent.change(screen.getByDisplayValue('Dev User'), { target: { value: 'Edited' } })
    expect(onDirtyChange).toHaveBeenLastCalledWith(true)

    fireEvent.click(screen.getByRole('button', { name: /Save search config/i }))
    await waitFor(() => expect(save.getSentBody()).not.toBeNull())
    // The saved snapshot becomes the new clean baseline.
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false))
  })

  it('renders FastAPI 422 field errors inline', async () => {
    stubSearchSave({
      status: 422,
      body: {
        detail: [
          {
            loc: ['body', 'roles', 'target_titles', 'preferred'],
            msg: 'List should have at least 1 item',
            type: 'too_short',
          },
          {
            loc: ['body', 'scrape_preferences', 'max_results_per_task'],
            msg: 'Input should be less than or equal to 200',
            type: 'less_than_equal',
          },
          {
            loc: ['body', 'work_constraints', 'max_travel_days'],
            msg: 'Input should be less than or equal to 365',
            type: 'less_than_equal',
          },
          {
            loc: ['body', 'scrape_preferences', 'linkedin_experience_codes'],
            msg: 'Input should be a valid LinkedIn experience code',
            type: 'literal_error',
          },
        ],
      },
    })
    renderForm({ initial: EXISTING, policies: null })

    fireEvent.click(screen.getByRole('button', { name: /Save search config/i }))

    expect(await screen.findByText(/List should have at least 1 item/i)).toBeInTheDocument()
    expect(screen.getByText(/less than or equal to 200/i)).toBeInTheDocument()
    expect(screen.getByText(/less than or equal to 365/i)).toBeInTheDocument()
    expect(screen.getByText(/valid LinkedIn experience code/i)).toBeInTheDocument()
  })
})
