export interface JobSummary {
  dedup_hash: string
  source: string | null
  source_url: string | null
  title: string | null
  company: string | null
  location: string | null
  posted_at: string | null
  remote_classification: string | null
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

export interface Filters {
  minScore: string
  maxScore: string
  remoteClassification: string[]
  minPostedAt: string
  maxPostedAt: string
  company: string
}
