# Evaluation results (ai mode)

Run at 2026-11-02 21:43. **8/10 correct in ai mode (18.5s total)**

| File | Expected | System | OK | Reasons | Time (s) |
|---|---|---|---|---|---|
| supplier-pack-01.pdf | Approve | Approve | ✅ | - | 2.51 |
| supplier-pack-02.pdf | Approve | Approve | ✅ | - | 2.53 |
| supplier-pack-03.pdf | Reject | Reject | ✅ | [R1] Unit price 229 is 9.05% above the maximum 210 (reject above 3%). | 2.44 |
| supplier-pack-04.pdf | Needs a person to check | Needs a person to check | ✅ | [H1] Unit price 6.65 is 2.31% above the maximum 6.5 (within the 3% band a person must approve). | 2.47 |
| supplier-pack-05.pdf | Reject | Reject | ✅ | [R2] Advance payment is 40%, more than the 20% allowed. | 2.86 |
| supplier-pack-06.pdf | Reject | Reject | ✅ | [R3] The contract has no late-delivery penalty clause. | 2.64 |
| supplier-pack-07.pdf | Needs a person to check | Reject | ❌ | [R4] Supplier TIN and BIN are missing. | 0.63 |
| supplier-pack-08.pdf | Reject | Reject | ✅ | [R4] Supplier TIN and BIN are missing. | 0.51 |
| supplier-pack-09.pdf | Needs a person to check | Reject | ❌ | [R4] Supplier TIN and BIN are missing. | 0.61 |
| supplier-pack-10.pdf | Reject | Reject | ✅ | [R4] Supplier TIN and BIN are missing. | 1.33 |
