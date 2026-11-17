# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend replay, nhãn judge lưu sẵn trong CSV; FAIL = lớp dương).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** — tp 24, fp 4, fn 6, tn 66 | **dùng** (non-blocking, chỉ cho tone) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** (κ, R dưới sàn) — tp 9, fp 0, fn 21, tn 70 | **loại** |

Tỉ lệ fail sau hiệu chỉnh Rogan-Gladen: tone 0.28 → **0.30**; helpful 0.09 → **0.30** (judge helpful báo thấp hơn thực tế hơn 3 lần).

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã. Rubric: liệt kê đại từ chuẩn ("anh/chị", "LogiX") và cấm tiểu từ thân mật (nha, nhé) với khách khiếu nại. |
| 2 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge bám vào "Dạ, vui lòng". Rubric: câu mệnh lệnh / chặn khách liên hệ là FAIL dù có kính ngữ. |
| 3 | H-051 "LogiX đã refund 90.000đ…" | FAIL | PASS | Người | CS LogiX cho phép từ "refund". Rubric: thêm whitelist thuật ngữ được phép, judge không phạt vì tiếng Anh. |
| 4 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | Người | Hứa ngoài kết quả hệ thống — đây là lỗi nội dung (gần FM-08), không phải tone. Rubric tone loại ra; chấm bằng code `reply_matches_ledger`. |
| 5 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện…" | FAIL | PASS | **Judge** | Ghi chú dataset: nhãn người sai (đọc nhầm ticket). Hành động: sửa nhãn người, ghi lại trong changelog nhãn; không sửa rubric. |
| 6 | H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Rubric: emoji cười trong ngữ cảnh khiếu nại = FAIL. |
| 7 | H-094 "Da, LogiX da hoan…" (mất dấu) | PASS | FAIL | Người | Rubric: tiếng Việt không dấu / dịch máy = FAIL. |
| 8 | HL-015 "đã hoàn 55.000đ cho đơn O-112" (helpful) | PASS | FAIL | Người | Ledger ghi 40.000đ. Judge không thấy ledger nên **không thể** chấm đúng tiền — 18/21 lỗi judge helpful bỏ sót là "sai tiền". |
| 9 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." (helpful) | PASS | FAIL | Người | Sai xưng hô + không nói kết quả; judge coi là "đã trả lời". |

## Kết luận
- **tone_ok dùng được**: κ=0.757, P=0.857, R=0.80 đều qua sàn. Phần lớn bất đồng (7/10) là judge dễ dãi với giọng suồng sã/ra lệnh/emoji/mất dấu → sửa rubric bằng ví dụ FAIL cụ thể ở trên rồi calibrate lại. Chỉ dùng làm metric theo dõi, không chặn release về tiền.
- **helpful bị loại**: recall 0.30 (bỏ 21/30 reply tệ), κ=0.375 < 0.6. Ma trận nhầm lẫn cho thấy judge gần như luôn nói PASS (fp=0 nên P=1.0 là ảo — một judge "luôn PASS" cũng có P không xác định/cao). 18/21 lỗi bỏ sót là **sai số tiền so với ledger**: judge chỉ đọc reply, không đọc ledger, nên về cấu trúc không thể chấm tiêu chí này. Thay bằng grader code `reply_matches_ledger` (FM-08) + `refund_amount_correct`.
- Không dùng judge nào làm gate cho tiền / approval (quy tắc: tiền và phê duyệt luôn chấm bằng code).
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng/tiêu chí); cần nhãn người mới để có held-out thật. Có ít nhất 1 nhãn người sai (H-081) → cần quy trình 2 người gán nhãn cho case bất đồng.
