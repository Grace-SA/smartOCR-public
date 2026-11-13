# smartOCR milestone status

| Stage | State | Evidence / exit condition |
|---|---|---|
| Local workflow baseline | Implemented; historical checks pass | See DEVELOPMENT.md; generalisation remains weak |
| Private source repository | Preparing | Source-only commit, no receipt data; verify remote private flag and commit |
| Real receipt dataset | Inventory pending | 276 archive entries identified; validate pixels, duplicates and grouped split |
| Reference annotations | Pending | Evidence regions, ambiguity labels; no prediction-derived ground truth |
| Speed and extraction comparison | Pending | Same inputs; median/P95/batch latency plus field accuracy and false confirmations |
| Competitor workflow research | Started | Official source-backed task comparisons and concrete UI decisions |
| Revised interaction | Pending | Desktop/mobile, selective review, export preview, override preservation |
| Untouched holdout evaluation | Pending | Frozen code/settings, first attempts, honest denominators |

Known issues: incomplete merchant/logo semantics; missing final totals; conservative review routing; repeated model loading; local environment coupling. Confidence is an evidence index, not a calibrated probability.
