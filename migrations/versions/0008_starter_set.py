"""starter_set

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-11

Onboarding starter set (specs/multi_user_design.md §5). A handful of neutral,
synthetic example postings so a newly invited member's feed isn't empty before
the admin has run their first overnight pipeline.

Two pieces:

- A few example postings in raw.job_postings, identified by the ``example-``
  dedup_hash prefix (created_by NULL — they're not anyone's manual entry).
  Inserted idempotently here; their *content* is shared, but they only become
  visible to a user once a per-user score row is seeded (see api/starter_set.py).
- app.users.starter_seeded_at — the once-per-user marker the API uses to seed
  the starter set on a member's first authenticated request and never again.

The postings carry no scores themselves; visibility is always via raw.job_scores
(``run_id = 'example-set'``), seeded per user at login. That keeps them
bulk-removable per user and excludable from real stats.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.users ADD COLUMN IF NOT EXISTS starter_seeded_at TIMESTAMPTZ"
    )

    # Synthetic, public, non-personal ads — safe for a public repo and trivially
    # swappable later. ON CONFLICT DO NOTHING keeps this idempotent across reruns.
    op.execute(
        """
        INSERT INTO raw.job_postings
            (dedup_hash, source, source_url, title, company, location,
             posted_at, description, remote_classification,
             salary_min_usd, salary_max_usd, salary_period)
        VALUES
            ('example-001', 'example', 'https://example.com/jobs/1',
             'Software Engineer', 'Example Remote Co', 'Remote, USA',
             '2026-06-01',
             'A sample posting so your feed has something to look at before '
             'your first real pipeline run. Build and maintain backend '
             'services in a small, friendly team.',
             'fully_remote', 120000, 160000, 'yearly'),
            ('example-002', 'example', 'https://example.com/jobs/2',
             'Data Engineer', 'Sample Analytics Inc', 'Remote, USA',
             '2026-06-02',
             'A sample posting. Design data pipelines and keep the warehouse '
             'tidy. This is example content, not a real opening.',
             'remote_with_monthly_travel', 130000, 175000, 'yearly'),
            ('example-003', 'example', 'https://example.com/jobs/3',
             'Product Manager', 'Demo Products LLC', 'Hybrid - Seattle, WA',
             '2026-06-03',
             'A sample posting to demonstrate the hybrid classification and '
             'how triage controls work. Replace it with real jobs once your '
             'pipeline runs.',
             'hybrid', 140000, 180000, 'yearly')
        ON CONFLICT (dedup_hash) DO NOTHING
        """
    )


def downgrade() -> None:
    # Deleting the example postings cascades to any seeded example-set score
    # rows (raw.job_scores FK is ON DELETE CASCADE).
    op.execute("DELETE FROM raw.job_postings WHERE dedup_hash LIKE 'example-%'")
    op.execute("ALTER TABLE app.users DROP COLUMN IF EXISTS starter_seeded_at")
