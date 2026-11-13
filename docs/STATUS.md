# smartOCR milestone status

| Stage | State | Evidence / exit condition |
|---|---|---|
| Local workflow baseline | Implemented; historical checks pass | See DEVELOPMENT.md; generalisation remains weak |
| Private source repository | Created and baseline pushed | [Grace-SA/smartOCR](https://github.com/Grace-SA/smartOCR); private flag verified; local data excluded |
| Real receipt dataset | Inventoried and initially partitioned | 276 decoded images; provisional 173 development, 49 reserved, 54 quarantine; grouping mistakes found and audited; transaction duplicates unresolved |
| Reference annotations | 39 development photos annotated | 30 complete records, nine partial photos; references frozen before each first attempt; independent human audit pending |
| Accuracy candidate | 30/30 complete development records match after revision | New 27-photo set improves 10/20 → 20/20 complete records using revised parsing and grounded visual review; one missing-merchant control remains unresolved; see ACCURACY_STAGE.md |
| Live image assistance | Enabled for uncertain imports when local model is installed | Source hash checks, review-only changed fields, immutable model attempts, bounded worker, preserved overrides; fresh runtime smoke passed |
| Processing speed | Production target unresolved | Expanded three-model first attempt: 46.5 minutes for 27 photos under shared workload; cache replay has no fresh runtime |
| Competitor workflow research | Documented workflow review complete | Smart Receipts, Expensify, Dext official help/AU listings; native paid-app usability trial not performed |
| Revised interaction | Second revision implemented and checked | Field-focused review, confirm/skip navigation, unsaved-edit protection, AU financial-year filters, ready-only export preview and immediate scoped insights; 1280px desktop / 319px mobile QA |
| Untouched holdout evaluation | Pending | Frozen code/settings, first attempts, honest denominators |

Known issues: incomplete merchant/logo semantics; missing final totals; conservative review routing; repeated model loading; local environment coupling. Confidence is an evidence index, not a calibrated probability.

Latest completed checks are recorded in DEVELOPMENT.md. First-attempt reserved-set evaluation remains pending. Correct development replay is not proof of universal 100% accuracy, production automatic precision or readiness.
