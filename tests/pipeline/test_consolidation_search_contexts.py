from pipeline.consolidation import _attach_search_contexts


def test_attach_search_contexts_preserves_remote_context_from_dropped_duplicate():
    canonical = [
        {
            "dedup_hash": "ddc-data-engineer",
            "source": "workday",
            "title": "Data Engineer",
            "description": "Longer ambiguous body wins dedup.",
        }
    ]
    postings = [
        canonical[0],
        {
            "dedup_hash": "ddc-data-engineer",
            "source": "workday",
            "title": "Data Engineer",
            "description": "Shorter body loses dedup.",
            "search_params": {
                "workplace": "remote",
                "job_type": "fulltime",
                "source_detail_location": "Remote; Washington, DC",
            },
        },
    ]

    _attach_search_contexts(canonical, postings)

    assert canonical[0]["search_contexts"] == [
        {
            "source": "workday",
            "workplace": "remote",
            "job_type": "fulltime",
            "source_detail_location": "Remote; Washington, DC",
        }
    ]
