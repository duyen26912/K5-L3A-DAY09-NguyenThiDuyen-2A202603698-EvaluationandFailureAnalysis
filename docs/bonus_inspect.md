# Bonus: port 3 grader sang Inspect AI và so khớp

Port ba grader code do nhóm viết, `approval_bypass`, `refund_amount_correct` và `reply_matches_ledger` (FM-08), sang **Inspect AI 0.3.291**, rồi so từng (item, seed) với kết quả của pydantic-evals trong report do `lab9.eval` sinh ra.

```bash
cd src
pip install -r requirements-bonus.txt
python -m lab9.inspect_port --shape seeded_regression --report reports/eval_seeded_regression.json
python -m lab9.inspect_port --shape swarm --spec config/metric_spec_v2.yaml --report reports/baseline_v2.json
# shape tạm từ công tắc lỗi (chỉ đăng ký trong bộ nhớ, không sửa variants.py, không ghi reports/)
python -m lab9.inspect_port --shape bonus_sibling_misreport --bugs no_override,sibling_refund,misreport,stale_clause,ignore_denied
python -m pytest -q -o addopts= tests/test_lab9_bonus_inspect.py
```

## Ánh xạ pydantic-evals → Inspect AI
| pydantic-evals | Inspect AI (`src/lab9/inspect_port.py`) |
|---|---|
| `Case` item@seed, `expected_output` = nhãn | `Sample(id="E-008@11")`, nhãn để trong `metadata["label"]` (không inline trong item) |
| task `run_one` → Trial | `@solver run_shape`: chạy shape bằng MockLLM, cất Trial vào `state.store`, `state.output` = reply cuối cho khách |
| `Evaluator.evaluate(ctx)` | `@scorer`: chỉ đọc Trial và nhãn, không gọi model |
| aggregate `sum` (an toàn) / `mean` | metric tự viết `count()` cho `approval_bypass`, `mean()` cho hai metric còn lại |
| model | `mockllm/model` có sẵn trong Inspect, không bao giờ được gọi (không cần API key) |

Ba scorer được **viết lại từ đặc tả** của từng grader, không import `lab9.graders`. Vì vậy hai bản khớp nhau từng dòng là bằng chứng cả hai chấm cùng một thứ, chứ không phải gọi cùng một hàm hai lần.

## Kết quả so khớp (ngày 18/11/2026)
| Shape | Report (run ID) | Sample | approval_bypass (PE / Inspect) | refund_amount_correct | reply_matches_ledger | Khớp |
|---|---|---|---|---|---|---|
| swarm (v1) | `E-swarm-20261117-130c` | 70 | 0 / 0 | 0.9857 / 0.9857 | 1.0 / 1.0 | 70/70 |
| fixed | `E-fixed-20261117-130c` | 70 | 0 / 0 | 1.0 / 1.0 | 1.0 / 1.0 | 70/70 |
| seeded_regression | `E-seeded_regression-20261117-130c` | 70 | 0 / 0 | 0.8571 / 0.8571 | 0.7857 / 0.7857 | 70/70 |
| swarm (v2) | `E-swarm-20261117-867f` | 140 | 0 / 0 | 0.9786 / 0.9786 | 1.0 / 1.0 | 140/140 |
| slice_regression (v2) | `E-slice_regression-20261117-867f` | 140 | 0 / 0 | 0.9357 / 0.9357 | 1.0 / 1.0 | 140/140 |
| bonus_sibling_misreport (tạm) | chạy trong bộ nhớ | 70 | **20 / 20** | 0.6429 / 0.6429 | 0.4286 / 0.4286 | 70/70 |

Kết luận: **0 chỗ lệch trên 560 sample × 3 grader.** Variant công khai không có lỗi bypass nào (`approval_bypass` luôn bằng 0), nên mình thêm một shape tạm bật `sibling_refund` để chứng minh scorer bypass của Inspect thật sự bắt lỗi (20 trial) và khớp với pydantic-evals.

## Nhận xét khi port
- Inspect hướng tới "model sinh câu trả lời rồi chấm", nên agent nhiều bước phải đóng gói thành một solver không gọi LLM. Trial (ledger, trace events) được cất trong `state.store`, vì `state.output` chỉ giữ được chuỗi.
- Inspect không có metric `sum`, nên metric an toàn dạng đếm phải tự viết bằng `@metric`.
- Inspect ghi log `.eval` cho từng sample (giải thích, câu trả lời). Đây là phần pydantic-evals không có sẵn khi chạy offline, tiện cho việc audit. Script ghi log vào thư mục tạm để không làm bẩn repo.
- Giới hạn: phải chạy tuần tự (`max_samples=1`) vì shape ghi SQLite và trace. Phần so khớp chỉ phủ 3/7 grader. Regex số tiền của FM-08 vẫn có cùng giới hạn ở cả hai bản (số viết bằng chữ chưa được hỗ trợ).
