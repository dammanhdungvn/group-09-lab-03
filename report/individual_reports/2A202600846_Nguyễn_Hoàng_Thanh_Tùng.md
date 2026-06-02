# Individual Report: Lab 3 - Chatbot vs ReAct Agent

- **Student Name**: Nguyễn Hoàng Thanh Tùng
- **Student ID**: 2A202600846
- **Date**: 06/01/2026

---

## I. Technical Contribution (15 Points)

*Describe your specific contribution to the codebase (e.g., implemented a specific tool, fixed the parser, etc.).*

- **Modules Implementated**: `src/agent/agent.py`, `src/telemetry/logger.py`, `src/telemetry/metrics.py`, `src/retail/hybrid_advisor.py`, `src/ui/server.py`, `src/ui/static/index.html`, `tests/test_react_agent.py`, `tests/test_hybrid_advisor.py`
- **Code Highlights**:
  - Tham gia hoàn thiện vòng lặp ReAct trong `src/agent/agent.py`, gồm các bước `Thought`, `Action`, `Observation` và `Final Answer`, đồng thời bắt buộc agent phải có ít nhất một tool observation hợp lệ trước khi trả lời.
  - Bổ sung parser cho `Action: tool_name({...})`, hỗ trợ JSON object, bỏ code fence nếu model trả lời trong markdown và tách argument an toàn hơn bằng `_split_args()` để giảm lỗi khi tham số có dấu phẩy hoặc chuỗi.
  - Cải thiện system prompt để mô tả rõ tool schema, tên tool hợp lệ, quy tắc không tự bịa số liệu tồn kho/doanh số và ví dụ Action đúng định dạng JSON.
  - Thêm cơ chế retry khi LLM trả `Final Answer` quá sớm hoặc không sinh đúng ReAct format. Agent sẽ gửi prompt hiệu chỉnh protocol thay vì chấp nhận câu trả lời chưa có dữ liệu.
  - Kết nối trace của agent với `HybridRetailStockAdvisor`: chuyển lịch sử tool call thành `ToolTrace`, ghi số bước LLM, trạng thái parser/tool/final answer và trả metrics cho UI.
  - Tham gia kiểm thử các case rủi ro trong `tests/test_react_agent.py` và `tests/test_hybrid_advisor.py`: trả lời sớm, action kèm final answer, parser error, hallucinated tool, timeout, strict LLM mode và hybrid fallback.
- **Documentation**: Phần tôi phụ trách nằm ở lớp điều phối giữa LLM và retail tools. `ReActAgent` nhận prompt từ `HybridRetailStockAdvisor`, tạo system prompt có danh sách tool trong `RetailTools.tool_specs()`, gọi LLM từng bước, parse `Action`, thực thi tool và nối `Observation` vào lịch sử. Sau khi agent có đủ bằng chứng, câu trả lời cuối được đưa về UI cùng trace để người dùng thấy rõ agent đã dựa trên dữ liệu nào trước khi khuyến nghị nhập hàng hoặc giảm giá.

---

## II. Debugging Case Study (10 Points)

*Analyze a specific failure event you encountered during the lab using the logging system.*

- **Problem Description**: Một lỗi thường gặp là LLM trả lời trực tiếp kiểu `Final Answer: P001 cần nhập thêm` ngay ở bước đầu, khi chưa gọi `get_inventory`, `detect_stockout_risk` hoặc `recommend_reorder_quantity`. Nếu chấp nhận kết quả này, agent sẽ giống chatbot thường và có nguy cơ hallucinate số liệu.
- **Log Source**: `src/agent/agent.py` ghi `AGENT_START`, `AGENT_STEP` và khi gặp lỗi protocol thì ghi `AGENT_PROTOCOL_RETRY`. Case này được kiểm chứng trong `tests/test_react_agent.py::test_react_agent_retries_when_llm_answers_before_tool_use`. Các lỗi nặng hơn cũng được log bằng `PARSER_ERROR`, `TOOL_NOT_FOUND` và được `HybridRetailStockAdvisor` ghi tiếp thành `RETAIL_AI_FALLBACK`.
- **Diagnosis**: Nguyên nhân đến từ việc model cố đưa ra đáp án theo thói quen chatbot thay vì tuân thủ ReAct. Với bài toán tồn kho, câu trả lời trước khi có observation là không đáng tin vì model chưa đọc dữ liệu JSON của hệ thống. Đây là lỗi prompt/protocol nhiều hơn là lỗi retail data.
- **Solution**: Tôi tham gia sửa bằng cách thêm quy tắc "Before any Final Answer, you must complete at least one valid tool call" trong system prompt, kiểm tra `agent.history` trước khi nhận final answer và tạo `_build_protocol_retry_prompt()` để ép model quay lại format `Thought` + `Action`. Nếu model vẫn sai hoặc gọi tool không tồn tại, hệ thống đánh dấu trạng thái lỗi để hybrid mode fallback về base rules thay vì trả lời thiếu căn cứ.

---

## III. Personal Insights: Chatbot vs ReAct (10 Points)

*Reflect on the reasoning capability difference.*

1.  **Reasoning**: Khối `Thought` giúp agent chia câu hỏi nhập hàng thành từng bước có kiểm chứng: cần tồn kho hiện tại, cần lịch sử bán 7/30 ngày, cần rủi ro hết hàng, sau đó mới tính lượng nhập hoặc khuyến mãi. Chatbot trực tiếp có thể trả lời nghe hợp lý, nhưng không bắt buộc phải chứng minh nó đã dùng dữ liệu thật.
2.  **Reliability**: Agent có thể tệ hơn chatbot khi model sinh sai format `Action`, gọi tool không có trong danh sách, lặp quá nhiều bước hoặc provider bị timeout. Vì vậy tôi thấy ReAct không chỉ là prompt hay, mà phải có parser, max steps, logging, validation và fallback thì mới đáng dùng trong ứng dụng thật.
3.  **Observation**: Observation làm câu trả lời có tính "grounded" hơn. Khi `get_inventory` hoặc `detect_stockout_risk` trả về stock, average daily sales và lead time, bước tiếp theo của agent không còn là đoán mà là chọn tool phù hợp dựa trên số liệu vừa nhận. Trace cũng giúp debug vì nhóm có thể nhìn lại từng Thought, Action và Observation thay vì chỉ nhìn câu trả lời cuối.

---

## IV. Future Improvements (5 Points)

*How would you scale this for a production-level AI agent system?*

- **Scalability**: Tách ReAct execution thành service riêng hoặc hàng đợi bất đồng bộ, cache kết quả tool trong một request, lưu session trace vào database và cho phép cấu hình max steps/timeout theo loại câu hỏi.
- **Safety**: Thêm schema validator chặt hơn cho tool arguments, chặn tool call ngoài whitelist trước khi thực thi, thêm supervisor kiểm tra final answer có thật sự dựa trên observation và ẩn toàn bộ thông tin nhạy cảm như API key khỏi log.
- **Performance**: Theo dõi latency/token theo từng provider, dùng fallback sớm khi LLM chậm, gom các tool call có thể chạy hàng loạt và hiển thị dashboard để so sánh chất lượng giữa `base`, `llm` và `hybrid`.

---

> [!NOTE]
> Submit this report by renaming it to `REPORT_[YOUR_NAME].md` and placing it in this folder.
