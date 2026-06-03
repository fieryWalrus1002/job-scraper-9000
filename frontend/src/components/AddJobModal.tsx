import { useState } from 'react'
import { useCreateManualJob } from '../hooks/useApplications'
import { APPLICATION_STATUSES } from '../types'
import type { ApplicationStatus } from '../types'
import styles from './AddJobModal.module.css'

interface Props {
  onClose: () => void
  onSuccess: () => void
}

export default function AddJobModal({ onClose, onSuccess }: Props) {
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState('')
  const [url, setUrl] = useState('')
  const [description, setDescription] = useState('')
  const [location, setLocation] = useState('')
  const [postedAt, setPostedAt] = useState('')
  const [fitScore, setFitScore] = useState<number | ''>('')
  const [status, setStatus] = useState<ApplicationStatus>('saved')
  const [apiError, setApiError] = useState<string | null>(null)

  const mutation = useCreateManualJob()

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setApiError(null)
    if (fitScore === '') { setApiError('Score is required.'); return }
    try {
      await mutation.mutateAsync({
        title: title.trim(),
        fit_score: fitScore,
        company: company.trim() || null,
        source_url: url.trim() || null,
        description: description.trim() || null,
        location: location.trim() || null,
        posted_at: postedAt || null,
        status,
      })
      onSuccess()
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setApiError(msg.startsWith('409') ? 'This job is already in the system.' : msg)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className={styles.addJobModal} onClick={(e) => e.stopPropagation()}>

        <div className="add-job-modal-header">
          <span className="add-job-modal-title">Add job manually</span>
          <button type="button" className="btn btn--ghost btn--icon" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <form className={styles.body} onSubmit={handleSubmit}>

          {/* Full Width Fields */}
          <div className={`${styles.formGroup} ${styles.fullWidth}`}>
            <label className="filter-label">Title *</label>
            <input
              className={styles.formInput}
              required
              placeholder="e.g. Senior Software Engineer"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          <div className={`${styles.formGroup} ${styles.fullWidth}`}>
            <label className="filter-label">Company</label>
            <input
              className={styles.formInput}
              placeholder="e.g. Acme Corp"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
            />
          </div>

          <div className={`${styles.formGroup} ${styles.fullWidth}`}>
            <label className="filter-label">Job URL</label>
            <input
              className={styles.formInput}
              type="text"
              placeholder="https://…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>

          <div className={`${styles.formGroup} ${styles.fullWidth}`}>
            <label className="filter-label">Job description</label>
            <textarea
              className={styles.formInput}
              style={{ minHeight: '100px', resize: 'vertical' }} /* Allows clean vertical expanding */
              placeholder="Copy-paste the job description here."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          {/* Half Width Fields (They don't get the fullWidth class modifier) */}
          <div className={styles.formGroup}>
            <label className="filter-label">Location</label>
            <input
              className={styles.formInput}
              placeholder="e.g. Remote, Seattle WA"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            />
          </div>

          <div className={styles.formGroup}>
            <label className="filter-label">Posted date</label>
            <input
              className={styles.formInput}
              type="date"
              value={postedAt}
              onChange={(e) => setPostedAt(e.target.value)}
            />
          </div>

          <div className={styles.formGroup}>
            <label className="filter-label">Your fit score * (1-5)</label>
            <select
              className={styles.formSelect}
              value={fitScore}
              onChange={(e) => setFitScore(e.target.value === '' ? '' : Number(e.target.value))}
            >
              <option value="">— pick one —</option>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>

          <div className={styles.formGroup}>
            <label className="filter-label">Initial status</label>
            <select
              className={styles.formSelect}
              value={status}
              onChange={(e) => setStatus(e.target.value as ApplicationStatus)}
            >
              {APPLICATION_STATUSES.map((s) => (
                <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>

          {apiError && <div className="text-error" style={{ fontSize: 13, gridColumn: '1 / -1' }}>{apiError}</div>}

          <div className={styles.modalActions}>
            <button type="button" className="btn btn--ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn" disabled={mutation.isPending}>
              {mutation.isPending ? 'Adding…' : 'Add job'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
