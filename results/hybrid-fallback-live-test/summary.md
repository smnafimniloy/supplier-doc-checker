# Evaluation results (hybrid mode)

Run at 2026-11-02 22:20. **10/10 correct in hybrid mode (154.6s total)**

| File | Expected | System | OK | Reasons | Time (s) |
|---|---|---|---|---|---|
| supplier-pack-01.pdf | Approve | Approve | ✅ | - | 22.44 |
| supplier-pack-02.pdf | Approve | Approve | ✅ | - | 8.89 |
| supplier-pack-03.pdf | Reject | Reject | ✅ | [R1] Unit price 229 is 9.05% above the maximum 210 (reject above 3%). | 24.89 |
| supplier-pack-04.pdf | Needs a person to check | Needs a person to check | ✅ | [X2] The AI reader and the rule-based parser disagree on item code (AI: None, parser: 'D'). A person should check which is right. | [R1] Cannot check this reliably because the item code could not be read with confidence. | [H2] Cannot check this reliably because the item code could not be read with confidence. | 5.32 |
| supplier-pack-05.pdf | Reject | Reject | ✅ | [R2] Advance payment is 40%, more than the 20% allowed. | 22.03 |
| supplier-pack-06.pdf | Reject | Reject | ✅ | [R3] The contract has no late-delivery penalty clause. | 23.13 |
| supplier-pack-07.pdf | Needs a person to check | Needs a person to check | ✅ | [H2] Quantity 16,500 piece differs from the requested 20,000 by -17.5% (limit ±5%). | 8.24 |
| supplier-pack-08.pdf | Reject | Reject | ✅ | [R4] Supplier TIN and BIN are missing. | 22.37 |
| supplier-pack-09.pdf | Needs a person to check | Needs a person to check | ✅ | [X2] The AI reader and the rule-based parser disagree on item code (AI: None, parser: 'D'). A person should check which is right. | [R1] Cannot check this reliably because the item code could not be read with confidence. | [H2] Cannot check this reliably because the item code could not be read with confidence. | [H3] Payment terms are unclear: a range of 30 to 90 days instead of a fixed term, and part of it is outside 30 to 60 days. | [H6] Line amount 322,000 should be 50,000 × 6.4 = 320,000 (difference 2,000). | 7.51 |
| supplier-pack-10.pdf | Reject | Reject | ✅ | [R5] Delivery in 60 days is later than the 45-day limit. | 9.75 |
