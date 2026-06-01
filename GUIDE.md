# Retail Stock Advisor

## Ý tưởng dự án

Retail Stock Advisor là một ReAct-style agent cho cửa hàng bán lẻ nhỏ. Agent không tự bịa dữ liệu; mọi khuyến nghị đều dựa trên mock dataset có kiểm soát trong `data/retail`.

Bài toán sản phẩm:

- Sản phẩm bán chạy dễ hết hàng trước khi nhà cung cấp giao kịp.
- Sản phẩm bán chậm bị nhập dư và chiếm vốn.
- Quản lý không có thời gian đọc báo cáo tồn kho, bán hàng thủ công.
- Cửa hàng cần câu trả lời hành động được: nên nhập gì, nhập bao nhiêu, nên giảm giá gì.

Luồng agent:

1. `get_inventory(product_id | category)` lấy tồn kho hiện tại.
2. `get_sales_history(product_id, days)` đọc lịch sử bán 7 hoặc 30 ngày.
3. `calculate_sell_through_rate(product_id)` tính tốc độ bán so với tồn kho.
4. `detect_stockout_risk(product_id)` phát hiện nguy cơ hết hàng.
5. `detect_slow_moving_items(category)` tìm mặt hàng tồn chậm.
6. `recommend_reorder_quantity(product_id)` đề xuất số lượng nhập theo lead time, safety stock, min order và pack size.
7. `get_seasonal_trends(period_id)` lấy xu hướng mua theo mùa/giai đoạn.
8. `recommend_seasonal_stock_plan(period_id, category)` đề xuất nhập trước theo hệ số nhu cầu mùa vụ.

## Kiến trúc

- `src/retail/models.py`: dataclass domain model.
- `src/retail/repositories.py`: repository đọc dữ liệu JSON, không cho agent truy cập file tùy ý.
- `src/retail/tools.py`: tools deterministic để giảm hallucination.
- `src/retail/advisor.py`: rule-based ReAct-style agent, có Thought/Action/Observation trace.
- `src/ui/server.py`: web UI dùng Python standard library.
- `src/ui/static/index.html`: giao diện thao tác cho quản lý cửa hàng.
- `tests/`: test cho tools, advisor và ReActAgent generic.

## Dữ liệu mùa vụ

Dữ liệu xu hướng theo thời điểm nằm trong `data/retail/seasonal_trends.json`. Các giai đoạn mẫu:

- `summer`: mùa hè, tăng nhu cầu nước uống và sữa.
- `rainy_season`: mùa mưa, tăng mì gói, cà phê gói và hàng gia dụng.
- `tet_holiday`: trước Tết, tăng nước uống, gạo, trứng và thực phẩm dự trữ.
- `back_to_school`: tựu trường, tăng sữa hộp, snack và nước uống tiện lợi.
- `month_end_budget`: cuối tháng, khách nhạy giá hơn và ưu tiên hàng thiết yếu.

## Cài đặt bằng `.venv`

Tạo môi trường ảo:

```powershell
python -m venv .venv
```

Kích hoạt môi trường:

```powershell
.\.venv\Scripts\Activate.ps1
```

Cài thư viện:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Nếu muốn chạy local GGUF model cho lab gốc, cài thêm:

```powershell
python -m pip install -r requirements-local.txt
```

## Chạy test

```powershell
python -m pytest
```

## Chạy giao diện

```powershell
python -m src.ui.server
```

Mở trình duyệt tại:

```text
http://127.0.0.1:8000
```

Prompt mẫu:

```text
Tuần này tôi nên nhập thêm mặt hàng nào và giảm giá mặt hàng nào?
```

Prompt theo mùa vụ:

```text
Trước Tết tôi nên chuẩn bị thêm mặt hàng nào và đẩy bán mặt hàng nào?
```

## Cách giảm hallucination

- Agent chỉ đọc dữ liệu từ `data/retail`, không dùng web search.
- Tool trả về số liệu có cấu trúc, không trả văn bản mơ hồ.
- Nếu thiếu `product_id`, tồn kho, sales history hoặc supplier rule, repository trả lỗi rõ ràng.
- UI hiển thị trace để người chấm thấy agent đã gọi tool nào và kết luận dựa trên observation nào.

## Engineering rules đã áp dụng

- Clean Architecture: tách domain model, repository, tools, advisor và UI.
- SOLID/KISS/YAGNI: mỗi class có một trách nhiệm, chưa đưa framework nặng khi standard library đủ dùng.
- DRY: công thức reorder, sell-through và payload formatting nằm trong `RetailTools`.
- Error Handling: repository trả `RetailDataError`, ReActAgent log `PARSER_ERROR`, UI trả JSON error rõ ràng.
- Security: server chỉ serve `index.html`, giới hạn request body 16KB, không cho đọc path tùy ý.
- Performance: dữ liệu load một lần trong repository, tool tính toán trên mock dataset nhỏ, phản hồi thường dưới 100ms.
- Type Safety: dùng dataclass, Protocol, type hints và test cho behavior chính.

## Gợi ý demo để đạt điểm lab

- So sánh chatbot baseline trả lời cảm tính với advisor dùng tools.
- Chụp trace thành công: agent phát hiện Coca Cola, mì gói, trứng cần nhập thêm.
- Chụp trace khuyến mãi: agent phát hiện cookies, dish soap, toothpaste tồn chậm.
- Phân tích failure v1: nếu chỉ dùng tồn kho mà bỏ qua lead time, agent dễ khuyến nghị thiếu chính xác.
- Cải thiện v2: thêm supplier rules, pack size, safety stock và sell-through 30 ngày.
