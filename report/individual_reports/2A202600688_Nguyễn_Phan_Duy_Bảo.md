# Individual Report: Lab 3 - Chatbot vs ReAct Agent

- **Student Name**: Nguyễn Phan Duy Bảo
- **Student ID**: 2A202600688
- **Date**: 06/01/2026

---

## I. Technical Contribution (15 Points)

*Describe your specific contribution to the codebase (e.g., implemented a specific tool, fixed the parser, etc.).*

- **Modules Implementated**: `src/ui/server.py`, `src/ui/static/index.html`, `src/retail/hybrid_advisor.py`, `src/retail/models.py`, `src/telemetry/logger.py`, `tests/test_hybrid_advisor.py`, `README.md`
- **Code Highlights**:
  - Tham gia xây dựng web API trong `src/ui/server.py`, đặc biệt là endpoint `POST /api/ask` nhận `question`, `category`, `period_id`, `analysis_mode` và trả về `answer`, `metrics`, `trace`, danh sách nhập hàng, khuyến mãi và kế hoạch mùa vụ.
  - Bổ sung các endpoint hỗ trợ giao diện như `GET /api/products` và `GET /api/periods` để UI có thể lấy danh sách sản phẩm, danh mục và giai đoạn mùa vụ từ repository thay vì hard-code toàn bộ logic xử lý ở client.
  - Tham gia hoàn thiện giao diện `src/ui/static/index.html`: form nhập câu hỏi, chọn danh mục, chọn giai đoạn, chọn chế độ `base`/`llm`, bảng metrics, các tab nhập hàng, khuyến mãi, mùa vụ và trace.
  - Kết nối trạng thái AI trên UI với metrics từ `HybridRetailStockAdvisor`, giúp người dùng phân biệt rõ khi hệ thống chạy base rules, LLM thành công, LLM lỗi hoặc hybrid fallback về deterministic advisor.
  - Chuẩn hóa dữ liệu trả về qua `AdvisorResult` và `ToolTrace` để frontend có thể hiển thị từng bước `Thought`, `Action`, `Observation` thay vì chỉ hiển thị câu trả lời cuối.
  - Tham gia kiểm thử luồng hybrid trong `tests/test_hybrid_advisor.py`, gồm base mode không gọi LLM, strict LLM mode, fallback khi provider thiếu cấu hình, parser error, hallucinated tool và timeout.
- **Documentation**: Phần tôi tham gia nằm ở lớp trải nghiệm người dùng và tích hợp API. `RetailAdvisorHandler` nhận request từ web, gọi `HybridRetailStockAdvisor`, sau đó chuyển kết quả thành JSON để UI hiển thị. Nhờ có metrics và trace, người dùng có thể thấy không chỉ "nên nhập thêm gì" mà còn biết hệ thống đã dùng tool nào, dữ liệu nào và chế độ phân tích nào để đi đến khuyến nghị.

---

## II. Debugging Case Study (10 Points)

*Analyze a specific failure event you encountered during the lab using the logging system.*

- **Problem Description**: Khi chạy chế độ hybrid, LLM có thể bị lỗi cấu hình, timeout hoặc gọi sai tool. Nếu UI chỉ hiển thị câu trả lời cuối, người dùng sẽ không biết kết quả đến từ LLM thật hay từ fallback base rules, làm giảm khả năng đánh giá độ tin cậy của agent.
- **Log Source**: `src/retail/hybrid_advisor.py` ghi các event `RETAIL_AI_SUCCESS`, `RETAIL_AI_FALLBACK` và `RETAIL_AI_STRICT_ERROR`. `src/ui/server.py` trả `metrics` về frontend, trong đó có `analysis_mode`, `method_label`, `ai_attempted`, `ai_used`, `fallback_used`, `fallback_reason`, `ai_provider`, `ai_model` và `llm_steps`. Case fallback được kiểm chứng trong `tests/test_hybrid_advisor.py::test_hybrid_advisor_falls_back_when_provider_is_not_configured`.
- **Diagnosis**: Vấn đề không chỉ là LLM lỗi, mà là UI/API ban đầu chưa thể hiện đủ trạng thái nội bộ của agent. Với hệ thống ReAct, câu trả lời cần đi kèm provenance: agent đã gọi tool chưa, gọi bao nhiêu bước, có fallback không và lỗi là gì.
- **Solution**: Tôi tham gia đưa metrics AI vào response của `/api/ask` và hiển thị chúng ở khu vực AI status trên giao diện. Khi `fallback_used=True`, UI báo rõ hệ thống đã thử LLM nhưng chuyển sang base rules, kèm lý do rút gọn. Khi `ai_error` xuất hiện ở strict LLM mode, UI hiển thị trạng thái lỗi thay vì làm người dùng hiểu nhầm rằng kết quả vẫn đáng tin như bình thường.

---

## III. Personal Insights: Chatbot vs ReAct (10 Points)

*Reflect on the reasoning capability difference.*

1.  **Reasoning**: Chatbot thường chỉ trả lời một đoạn văn cuối cùng, nên người dùng khó biết nó dựa trên dữ liệu nào. ReAct agent tốt hơn vì mỗi khuyến nghị đều có trace: trước tiên suy nghĩ cần dữ liệu gì, sau đó gọi tool, nhận observation và mới tổng hợp câu trả lời.
2.  **Reliability**: Agent có thể kém ổn định hơn chatbot nếu provider chậm, model trả sai format hoặc tool call bị lỗi. Tuy nhiên, khi UI hiển thị rõ trạng thái `base`, `llm`, `fallback` và trace, người dùng có thể đánh giá kết quả minh bạch hơn thay vì tin mù quáng vào một câu trả lời nghe tự tin.
3.  **Observation**: Observation giúp biến câu trả lời từ cảm tính thành có căn cứ. Ví dụ bảng trace hiển thị `get_inventory`, `detect_stockout_risk` hoặc `recommend_seasonal_stock_plan` cùng dữ liệu trả về, nhờ đó người quản lý kho có thể kiểm tra nhanh vì sao một sản phẩm được đề xuất nhập thêm hoặc giảm giá.

---

## IV. Future Improvements (5 Points)

*How would you scale this for a production-level AI agent system?*

- **Scalability**: Tách API web và tác vụ LLM thành service riêng, thêm hàng đợi cho request chậm, cache danh sách sản phẩm/giai đoạn và hỗ trợ nhiều cửa hàng hoặc nhiều kho trong cùng giao diện.
- **Safety**: Thêm xác thực người dùng, giới hạn request body, validate dữ liệu đầu vào chặt hơn, ẩn thông tin lỗi nhạy cảm trên UI và chỉ hiển thị fallback reason ở mức đủ để debug.
- **Performance**: Thêm loading state chi tiết cho từng bước agent, đo latency từ frontend đến backend, lưu lịch sử trace để so sánh các lần chạy và tối ưu UI khi danh sách sản phẩm hoặc trace quá dài.

---

> [!NOTE]
> Submit this report by renaming it to `REPORT_[YOUR_NAME].md` and placing it in this folder.
