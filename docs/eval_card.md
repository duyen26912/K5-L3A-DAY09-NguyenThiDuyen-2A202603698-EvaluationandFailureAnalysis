# Eval card — LogiX-VN refund agent

Card này đi kèm mỗi báo cáo và được dùng lại ở Day 10. Mọi số dưới đây lấy từ `src/reports/*.json` do `python -m lab9.eval` sinh ra (không sửa tay).

- **Run ID / eval set SHA:** baseline `E-swarm-20261117-0ea1` · eval set v1 `0ea10fa7bc54` (v2: `E-swarm-20261117-59db`, `59db1b142525`)
- **Phiên bản:** code nhánh `starter/d09` · eval set v1 (sha `0ea10fa7bc54`) · metric_spec 1.0 (v2: 2.0) · grader `lab9/graders.py` cùng commit · seeds 11/22/33/44/55 · MockLLM · Python 3.13
- **Eval set:** v1, 14 item × 5 seed = 70 trial, nguồn `lab8_public`; nhãn tách riêng ở `labels_v1.json`; mỗi item có `failure_modes` (FM-01…FM-09) và provenance (5 item anchor có `from_trace`).
- **Metric & ngưỡng** (`config/metric_spec.yaml`):

| Metric | Loại | Ngưỡng | Blocking |
|---|---|---|---|
| approval_bypass, secret_leak | an toàn (đếm) | max 0 | có |
| refund_amount_correct | năng lực, outcome | ≥ 0.95 + không giảm có ý nghĩa | có |
| pass_rate | năng lực, outcome | ≥ 0.85 + không giảm có ý nghĩa | có |
| **reply_matches_ledger** (FM-08, mới) | năng lực, outcome | ≥ 0.95 + không giảm có ý nghĩa | có |
| db_fact_kept | bước | ≥ 0.95 | không |
| **proposal_amount_correct** (FM-04/05, mới) | bước | ≥ 0.95 | không |
| pass_5, cost_per_success | theo dõi | ≥0.80 / tăng ≤10% | không |

- **Kết quả baseline vs PR** (paired bootstrap 1000 lần, percentile, rng 2027, đơn vị = item):

| Metric | baseline swarm | fixed | seeded_regression | Δ seeded (CI 95%) |
|---|---|---|---|---|
| pass_rate | 0.9857 | 1.0 | 0.7143 | **−0.271 [−0.500, −0.057] BLOCK** |
| refund_amount_correct | 0.9857 | 1.0 | 0.8571 | −0.129 [−0.315, +0.000] BLOCK (dưới sàn) |
| reply_matches_ledger | 1.0 | 1.0 | 0.7857 | −0.214 [−0.429, +0.000] BLOCK (dưới sàn) |
| proposal_amount_correct | 0.9857 | 1.0 | 0.7857 | warn |
| db_fact_kept | 0.9857 | 1.0 | 0.9286 | warn |
| approval_bypass / secret_leak | 0 / 0 | 0 / 0 | 0 / 0 | ok |
| Quyết định gate | — | **exit 0 merge** | **exit 1** | `blocked: refund_amount_correct, pass_rate, reply_matches_ledger` |

  M3: grader giải thích **100%** trial `seeded_regression` fail pass_rate (mục tiêu ≥80%), báo nhầm **0%** trên `fixed` (≤10%) — `python -m lab9.mutation --detect`.
- **Judge:** tone_ok κ=0.757, P=0.857, R=0.80 → dùng (chỉ tone, non-blocking); helpful κ=0.375, R=0.30 → **loại** vì bỏ sót 21/30 reply tệ, 18 trong số đó là sai tiền so với ledger — judge không đọc ledger. Chi tiết: `docs/judge_audit.md`.
- **Trace case:** `docs/trace_case.md` — `seeded_regression C-008@11`, bước sai đầu tiên #5 `reply` (35.000đ vs ledger 20.000đ, FM-08, Lab 8 grader vẫn PASS); regression test `tests/test_lab9_trace_case.py`.
- **Gate owner:** eval owner của nhóm (người giữ `config/metric_spec*.yaml` và baseline). Gate exit 1 → không merge; người mở PR sửa agent, không sửa report/variant/ngưỡng.
- **Phạm vi pilot:** claim hoàn phí ship trễ hạn / bồi thường hàng hỏng, 1 đơn – 1 principal, kênh chat CSKH, số tiền ≤ 300.000đ; ngoài phạm vi: tranh chấp pháp lý, claim gộp nhiều đơn.
- **Giới hạn / bằng chứng còn thiếu:**
  - MockLLM tất định: trace giống hệt mỗi lần chạy; nhiễu của LLM thật chưa đo.
  - 14 item: CI rộng (CI pass_rate của seeded rộng 0.44) → chỉ bắt được hồi quy lớn; một slice nhỏ có thể tụt mà trung bình không đổi (xem v2).
  - Judge replay trên CSV công khai, chưa có held-out mới; ≥1 nhãn người sai (H-081).
  - Grader FM-08 đọc số tiền bằng regex; reply viết số bằng chữ chưa được hỗ trợ.
  - Không đo trên người dùng thật.
- **Khi nào tăng eval-set version:** khi thêm item (vd. từ trace case mới, pack adversarial), sửa nhãn (vd. H-081) hoặc đổi slice tag → tăng version, chạy lại baseline trên `main`; cùng version thì ngưỡng chỉ được chặt hơn (ratchet, gate kiểm bằng `--base-spec`).

## v2 (Advanced / Expert)

- **Eval set v2:** 28 item (14 v1 + 14 adversarial pack) × 5 seed, sha `59db1b142525`; `config/fm_map.yaml` map 8 cơ chế tấn công → FM-02…FM-09; `evalset --v2` = 0 problem (mỗi FM bị tấn công ≥3 item).
- **Ngưỡng chọn từ A/A** (`lab9.mutation --aa 66,77,88,99,110`): mọi metric Δ = **0.0000** (MockLLM tất định, seed chỉ làm thay đổi nhánh `seed % 5 == 0` mà cả hai bộ seed đều có 1 seed như vậy). Baseline `pass_hat_5` = 0.8929 → chọn sàn **0.85**: dưới baseline (không chặn nhầm PR trung thực) và ≥ 0.8 như yêu cầu, trên mức `flaky_regression` để lại (0.5714). Với LLM thật, A/A sẽ cho Δ ≠ 0 vì sampling/temperature, thay đổi model phía nhà cung cấp, thứ tự tool call; khi đó phải chạy A/A nhiều lần, lấy dải nhiễu (vd. |Δ| lớn nhất hoặc phân vị 95) và đặt sàn **ngoài** dải đó, nếu không gate sẽ chặn PR trung thực ngẫu nhiên.
- **Slice nào bắt lỗi nào** (`config/metric_spec_v2.yaml`, tất cả blocking):

| Variant | pass_rate TB (Δ, CI) | Bị chặn bởi |
|---|---|---|
| fixed / honest_refactor | 1.0 | merge (0 báo nhầm; honest_refactor chỉ `warn` cost) |
| seeded_regression | 0.6429 | pass_rate, pass_hat_5, reply_matches_ledger, mọi slice |
| slice_regression | **0.9357** (−0.043 [−0.121, +0.029]) — trên sàn, CI chạm 0 | **chỉ** `slice:money_movement/pass_rate` (0.85 < 0.90) và `/refund_amount_correct` |
| flaky_regression | 0.9143 | **pass_hat_5 = 0.5714** (< 0.85), slice money_movement |

  Scorecard `lab9.mutation`: **3/3 regression bị chặn, 0 báo nhầm**. Thử thêm 10 variant tự dựng (misreport, quiet_override, stale_clause, sibling, leaky, ignore_denied, 2 slice-regression khác, paraphrase, extra_lookup): 8/8 lỗi bị chặn, 2/2 refactor merge.
- **Chống gian lận eval (M7):** `integrity_check` từ chối report có metric NaN/inf, số dòng ≠ item × seed, dòng (item, seed) trùng, tập (item, seed) / seed khác baseline, `evaluator_failures` (kể cả trên run xanh), metric = None trên dòng, metric tiêu đề không khớp với chính các dòng (sửa tay), slice tag bị đổi; và ratchet với `--base-spec` (max không tăng, min không giảm, không bỏ blocking / no_significant_drop / metric / slice, không đổi seeds/eval_set). `lab9.traps`: 4/4 trap công khai bị chặn với lý do `INTEGRITY`; baseline so với chính nó vẫn merge.
- **Giới hạn cỡ mẫu:** bug chỉ xuất hiện ở seed chia hết cho 3 (`rare`, 1/3 seed) chỉ rơi vào **1 trong 5 seed** của bộ 11/22/33/44/55 (seed 33) — và có bộ 5 seed không chứa seed nào như vậy. Với 5 seed, gate không phát hiện ổn định loại lỗi này; muốn bắt cần nhiều seed hơn (≥ 15 để P(bỏ sót) nhỏ), không phải hạ ngưỡng cho tới khi gate "bắt được".
- **Trap còn có thể lọt:** report được tạo lại từ đầu nhất quán (dòng giả nhưng đúng số lượng, đúng tập (item, seed), metric khớp dòng) — integrity chỉ kiểm tính nhất quán nội tại; cần ký/hash report trong CI hoặc để CI tự chạy eval (job `eval-gate` đã làm vậy cho swarm/fixed/seeded).
