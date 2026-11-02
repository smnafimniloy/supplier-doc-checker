# Evaluation results (hybrid mode)

Run at 2026-11-02 22:18. **10/10 correct in hybrid mode (167.8s total)**

| File | Expected | System | OK | Reasons | Time (s) |
|---|---|---|---|---|---|
| supplier-pack-01.pdf | Approve | Approve | ✅ | - | 4.61 |
| supplier-pack-02.pdf | Approve | Approve | ✅ | - | 3.16 |
| supplier-pack-03.pdf | Reject | Reject | ✅ | [R1] Unit price 229 is 9.05% above the maximum 210 (reject above 3%). | 6.82 |
| supplier-pack-04.pdf | Needs a person to check | Needs a person to check | ✅ | [H1] Unit price 6.65 is 2.31% above the maximum 6.5 (within the 3% band a person must approve). | 21.81 |
| supplier-pack-05.pdf | Reject | Reject | ✅ | [R2] Advance payment is 40%, more than the 20% allowed. | 23.28 |
| supplier-pack-06.pdf | Reject | Reject | ✅ | [R3] The contract has no late-delivery penalty clause. | 20.97 |
| supplier-pack-07.pdf | Needs a person to check | Needs a person to check | ✅ | [H2] Quantity 16,500 piece differs from the requested 20,000 by -17.5% (limit ±5%). | 21.61 |
| supplier-pack-08.pdf | Reject | Reject | ✅ | [R4] Supplier TIN and BIN are missing. | 21.74 |
| supplier-pack-09.pdf | Needs a person to check | Needs a person to check | ✅ | [X2] The AI reader and the rule-based parser disagree on item code (AI: None, parser: 'D'). A person should check which is right. | [R1] Cannot check this reliably because the item code could not be read with confidence. | [H2] Cannot check this reliably because the item code could not be read with confidence. | [H3] Payment terms are unclear: a range of 30 to 90 days instead of a fixed term, and part of it is outside 30 to 60 days. | [H6] Line amount 322,000 should be 50,000 × 6.4 = 320,000 (difference 2,000). | 21.68 |
| supplier-pack-10.pdf | Reject | Reject | ✅ | [R5] Delivery in 60 days is later than the 45-day limit. | 22.07 |
