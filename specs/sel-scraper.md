# SEL Scraper

SEL uses Workday. See `specs/fix_sel.md` for the full technical spec (CXS POST API, GUID verification).

Known working GUIDs as of 2026-05-13:

```python
loc_map    = {"pullman_wa": "df72ee3ddefc1018ebf01de718624e22"}
worker_map = {"regular": "96e1096563ef1014e495031ab61a6dff", "temporary": "96e1096563ef1014e495069e83966e00"}
time_map   = {"full_time": "b0630d66f89e1013409e4b1a1a91c123", "part_time": "b0630d66f89e1013409e4ae8d2c9c122"}
```

Work tracked on GitHub — `gh issue list` or <https://github.com/fieryWalrus1002/job-scraper-9000/issues>
