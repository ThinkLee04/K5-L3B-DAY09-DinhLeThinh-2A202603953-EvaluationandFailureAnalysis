# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case đã ghi nhận: FM-03 trên C-002@55

Run `seeded_regression` and `fixed` with the same claim and seed:

```bash
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 55
python -m lab9.trace_case --shape fixed --claim C-002 --seed 55
```

| Trường | Bằng chứng |
|---|---|
| Trial | `seeded_regression C-002@55`; Lab 8 grader fails with `status resolved != denied`. |
| Triệu chứng | Reply says a 20,000đ refund; ledger has one 20,000đ row, while label expects denied and 0đ. |
| Bước sai đầu tiên | Event 3: `model_override`, `delay_days=5`. The DB order O-202 has 2 delay days; the ticket claim of 5 makes the quote eligible. |
| Vì sao là bước đầu tiên | Handoff and investigator lookup are correct. Event 2 returns O-202 with delay 2; the earliest contradiction is introduced at event 3. |
| Failure mode | FM-03 (`ticket_trust`). |
| Đối chứng | `fixed C-002@55` keeps DB delay 2, quote is 0, reply says not eligible, ledger remains 0 and Lab 8 grader passes. |
| Regression test | `tests/test_lab9_trace_case.py::test_c002_seed_55_detects_ticket_trust_regression` asserts the failing variant and passing fixed control. |
| Chưa chắc chắn | This proves the deterministic MockLLM case only; it does not estimate real-model frequency. |

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
