# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-008 --seed 11
python -m lab9.trace_case --shape fixed --claim C-008 --seed 11   # đối chứng
```

## Case: `seeded_regression C-008@11` — reply nói 35.000đ, ledger ghi 20.000đ

```
== seeded_regression C-008@11  lab8 grader: PASS (ok)
   1 handoff            {"request_id": "REQ-C-008", ... "allowed_tools": ["lookup_order", "lookup_policy", ...
   2 investigator       {"lookup_order": {"visible": true, "reason": "ok", "order": {"order_id": "O-808", ...
   3 quote              {"amount_vnd": 35000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], ...
   4 refund_history     {"refund_count": 0, "refunded_vnd": 0}
   5 reply              {"text": "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."}
-- ledger vs label
  refund_vnd     ledger=20000    label=20000
  refund_count   ledger=1        label=1
  status         result=resolved label=resolved
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-008@11`, report `E-seeded_regression-20261117-0ea1` (item E-008, cả 5 seed đều lỗi) |
| Triệu chứng | Grader Lab 8 **PASS** (status + ledger đúng). `reply_matches_ledger` FAIL: reply "đã hoàn 35.000đ", ledger chỉ có 20.000đ (host giới hạn theo approval A-008). Khách được hứa 15.000đ không tồn tại. |
| Bước sai đầu tiên | Event **#5 `reply`** — `"Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."` |
| Vì sao là bước *đầu tiên* | #1–#2 handoff/investigator đúng đơn O-808 của P-100; #3 quote 35.000 khớp nhãn `proposal_amount=35000`; #4 refund_history = 0 nên bước trừ trước không đổi số đề xuất; host commit 20.000 (đúng nhãn `refund_vnd`). Sai chỉ bắt đầu khi reply lấy **số đề xuất** thay vì **số host đã ghi** (`said = proposal` khi bật `pre_deducted`). |
| Failure mode | **FM-08 misreport** (`docs/failure_taxonomy.md`) |
| Đối chứng | `fixed C-008@11`: cùng #1–#3, không có #4, event #4 `reply` "đã hoàn **20.000đ**" = ledger → `reply_matches_ledger` PASS |
| Regression test | `tests/test_lab9_trace_case.py`: `test_lab9_trace_case_c008_misreport_is_caught` (assert Lab 8 PASS nhưng `ReplyMatchesLedger` FAIL trên `seeded_regression`) và `test_lab9_trace_case_c008_fixed_is_clean` (PASS trên `fixed`). Cả hai chạy trong job `eval-gate` (`-m student -k "lab9 and not advanced"`). Thêm metric blocking `reply_matches_ledger` (min 0.95 + no_significant_drop) vào `metric_spec.yaml`; gate chặn `seeded_regression` ở metric này (Δ −0.214). |
| Chưa chắc chắn | Trace không ghi `effect` host trả về, nên không thấy trực tiếp lý do host cap 20.000 (suy ra từ approval A-008 và nhãn). Grader đọc số tiền bằng regex `\d{1,3}(.\d{3})+ đ`: reply viết chữ ("ba mươi lăm nghìn") hoặc nhiều số (phí + tổng) sẽ cần grader chặt hơn. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
