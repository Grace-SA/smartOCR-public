# smartOCR milestone status

| Stage | State | Evidence / exit condition |
|---|---|---|
| Local workflow baseline | Implemented; historical checks pass | See DEVELOPMENT.md; generalisation remains weak |
| Private source repository | Created and baseline pushed | [Grace-SA/smartOCR](https://github.com/Grace-SA/smartOCR); private flag verified; local data excluded |
| Real receipt dataset | Inventoried and initially partitioned | 276 decoded images; 173 development, 49 grouped holdout, 54 quarantine; transaction duplicates unresolved |
| Reference annotations | 12-image pilot complete | Ten complete records, two partial controls; assistant references, one transparently logged visual correction; human audit pending |
| Speed and extraction comparison | Four pilot runs complete; no fast route promoted | Three-model 405.6s / 7 of 10 complete records correct; structured fast route 86.2s / 5 of 10; see PHASE_SUMMARY.md |
| Competitor workflow research | Documented workflow review complete | Smart Receipts, Expensify, Dext official help/AU listings; native paid-app usability trial not performed |
| Revised interaction | Implemented and locally checked | Desktop/mobile, photo zoom, save-and-next, collapsed optional fields, scoped preview, stale-export rejection, override preservation |
| Untouched holdout evaluation | Pending | Frozen code/settings, first attempts, honest denominators |

Known issues: incomplete merchant/logo semantics; missing final totals; conservative review routing; repeated model loading; local environment coupling. Confidence is an evidence index, not a calibrated probability.

Latest checks: 171 Python tests, six Node tests and JavaScript syntax check passed. First-attempt held-out evaluation remains pending; these pilot measurements do not establish 100% accuracy or production readiness.
