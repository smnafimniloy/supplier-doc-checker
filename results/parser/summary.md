# Evaluation results (parser mode)

Run at 2026-11-02 22:46. **10/10 correct in parser mode (0.1s total)**

| File | Expected | System | OK | Reasons | Time (s) |
|---|---|---|---|---|---|
| supplier-pack-01.pdf | Approve | Approve | ✅ | - | 0.01 |
| supplier-pack-02.pdf | Approve | Approve | ✅ | - | 0.01 |
| supplier-pack-03.pdf | Reject | Reject | ✅ | [R1] Unit price 229 is 9.05% above the maximum 210 (reject above 3%). | 0.02 |
| supplier-pack-04.pdf | Needs a person to check | Needs a person to check | ✅ | [H1] Unit price 6.65 is 2.31% above the maximum 6.5 (within the 3% band a person must approve). | 0.01 |
| supplier-pack-05.pdf | Reject | Reject | ✅ | [R2] Advance payment is 40%, more than the 20% allowed. | 0.01 |
| supplier-pack-06.pdf | Reject | Reject | ✅ | [R3] The contract has no late-delivery penalty clause. | 0.01 |
| supplier-pack-07.pdf | Needs a person to check | Needs a person to check | ✅ | [H2] Quantity 16,500 piece differs from the requested 20,000 by -17.5% (limit ±5%). | 0.01 |
| supplier-pack-08.pdf | Reject | Reject | ✅ | [R4] Supplier TIN and BIN are missing. | 0.01 |
| supplier-pack-09.pdf | Needs a person to check | Needs a person to check | ✅ | [H3] Payment terms are unclear: a range of 30 to 90 days instead of a fixed term, and part of it is outside 30 to 60 days. | [H6] Line amount 322,000 should be 50,000 × 6.4 = 320,000 (difference 2,000). | 0.01 |
| supplier-pack-10.pdf | Reject | Reject | ✅ | [R5] Delivery in 60 days is later than the 45-day limit. | 0.01 |
