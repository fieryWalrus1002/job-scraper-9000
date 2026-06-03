export interface JobSummary {
  dedup_hash: string
  source: string | null
  source_url: string | null
  title: string | null
  company: string | null
  location: string | null
  posted_at: string | null
  remote_classification: string | null
  salary_min_usd: number | null
  salary_max_usd: number | null
  salary_period: string | null
  fit_score: number | null
  confidence: string | null
  score_rationale: string | null
  failure_reason: string | null
  scored_at: string
}

export interface JobListResponse {
  total: number
  limit: number
  offset: number
  items: JobSummary[]
}

export interface AiFitDetail {
  fit_score: number | null
  confidence: string | null
  score_rationale: string | null
  top_matches: string[]
  gaps: string[]
  hard_concerns: string[]
  core_job_duties: string[]
  [key: string]: unknown
}

export interface JobDetail {
  dedup_hash: string
  source: string | null
  source_job_id: string | null
  source_url: string | null
  title: string | null
  company: string | null
  location: string | null
  posted_at: string | null
  description: string | null
  scraped_at: string | null
  remote_classification: string | null
  salary_min_usd: number | null
  salary_max_usd: number | null
  salary_period: string | null
  fit_score: number | null
  confidence: string | null
  score_rationale: string | null
  ai_fit_detail: AiFitDetail | null
  pipeline_metadata: Record<string, unknown>
  run_id: string
  scored_at: string
  model: string
  provider: string
  profile_version: string
  failure_reason: string | null
  metadata: Record<string, unknown>
  ingested_at: string
}

export interface Filters {
  minScore: string
  maxScore: string
  remoteClassification: string[]
  minPostedAt: string
  maxPostedAt: string
  company: string
  minSalaryK: string
  maxSalaryK: string
}
