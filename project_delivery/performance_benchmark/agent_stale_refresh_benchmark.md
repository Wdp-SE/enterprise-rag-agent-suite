# Agent Full Refresh vs Stale Local Refresh

The synthetic workflow contains 8 sections.
After V2 activation, exactly 2 sections become
STALE; the remaining 6 stay valid.

| Metric | Full refresh | Local refresh |
|---|---:|---:|
| Sections executed | 8 | 2 |
| RAG calls | 8 | 2 |
| P50 elapsed | 262.909 ms | 197.382 ms |
| P95 elapsed | 313.942 ms | 246.320 ms |

- Preserved sections: **6 / 8 (75.000%)**
- RAG-call reduction: **75.000%**
- P50 elapsed reduction: **24.924%**
- Effect: **MODERATE**

Freshness selected exactly the two changed documents, untouched sections were
not re-executed, and the final semantic output matched a full V2 refresh.
