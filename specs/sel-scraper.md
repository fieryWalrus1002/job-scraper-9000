# Scraping SEL Workday jobs portal


I tried comparing the endpoints over days.

The dict I made on 5-12-26:
``` python
# Mapping dictionaries (Moved here or kept in a central mapping file)
loc_map = {"pullman_wa": "df72ee3ddefc1018ebf01de718624e22"}
worker_map = {
    "regular": "96e1096563ef1014e495031ab61a6dff",
    "temporary": "96e1096563ef1014e495069e83966e00"
}
time_map = {
    "full_time": "b0630d66f89e1013409e4b1a1a91c123",
    "part_time": "b0630d66f89e1013409e4ae8d2c9c122"
}

```

It looks like the location endpoint still matches on 2026-05-13:

``` bash 

# Search for jobs in Pullman, WA, 5-13-26
# https://selinc.wd1.myworkdayjobs.com/en-US/SEL?locations=df72ee3ddefc1018ebf01de718624e22

```