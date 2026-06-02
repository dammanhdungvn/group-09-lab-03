# Lab 3 - Retail Stock Advisor ReAct Agent

Dự án minh họa chatbot tư vấn tồn kho bán lẻ dùng mô hình ReAct Agent. Ứng dụng có giao diện web đơn giản để đặt câu hỏi, chọn danh mục/mùa vụ và nhận gợi ý nhập hàng, giảm giá hoặc kế hoạch tồn kho theo mùa.

Hệ thống hỗ trợ nhiều chế độ phân tích:

- `base`: dùng luật tính toán cố định từ dữ liệu JSON.
- `llm`: dùng ReAct Agent và LLM, không fallback.
- `hybrid`: thử ReAct Agent trước, nếu LLM lỗi hoặc cấu hình chưa đúng thì fallback về luật cố định.

## Tác giả

| Họ tên | MSSV |
| --- | --- |
| Đàm Mạnh Dũng | 2A202600741 |
| Nguyễn Hoàng Thanh Tùng | 2A202600846 |
| Lê_Bá_Chiến | 2A202600755 |
| Nguyễn Phan Duy Bảo | 2A202600688 |

## Tổng quan thư mục

```text
.
|-- data/
|   `-- retail/
|       |-- inventory.json          # Dữ liệu tồn kho hiện tại
|       |-- products.json           # Danh sách sản phẩm
|       |-- sales_history.json      # Lịch sử bán hàng
|       |-- seasonal_trends.json    # Hệ số mùa vụ
|       `-- supplier_rules.json     # Quy tắc nhà cung cấp
|-- report/
|   |-- group_report/               # Mẫu báo cáo nhóm
|   `-- individual_reports/         # Mẫu báo cáo cá nhân
|-- src/
|   |-- agent/
|   |   `-- agent.py                # Vòng lặp ReAct: Thought, Action, Observation
|   |-- core/
|   |   |-- llm_provider.py         # Interface chung cho LLM provider
|   |   |-- provider_factory.py     # Tạo provider theo biến môi trường
|   |   |-- openai_provider.py      # Provider OpenAI
|   |   |-- gemini_provider.py      # Provider Gemini
|   |   |-- dashscope_provider.py   # Provider DashScope/Qwen
|   |   `-- local_provider.py       # Provider local GGUF qua llama-cpp
|   |-- retail/
|   |   |-- advisor.py              # Bộ tư vấn deterministic/base rules
|   |   |-- hybrid_advisor.py       # Kết hợp LLM ReAct và base rules
|   |   |-- models.py               # Dataclass/schema dữ liệu
|   |   |-- repositories.py         # Đọc dữ liệu retail từ JSON
|   |   `-- tools.py                # Các tool cho ReAct Agent
|   |-- telemetry/
|   |   |-- logger.py               # Ghi log sự kiện
|   |   `-- metrics.py              # Theo dõi request/latency/token
|   `-- ui/
|       |-- server.py               # HTTP server chạy web app
|       `-- static/index.html       # Giao diện người dùng
|-- tests/                          # Unit tests cho agent, provider và retail tools
|-- .env.example                    # Mẫu cấu hình môi trường
|-- requirements.txt                # Thư viện Python chính
|-- requirements-local.txt          # Thư viện để chạy model local
|-- GUIDE.md                        # Hướng dẫn lab
|-- EVALUATION.md                   # Gợi ý đánh giá
|-- SCORING.md                      # Tiêu chí chấm điểm
`-- INSTRUCTOR_GUIDE.md             # Tài liệu cho giảng viên
```

## Yêu cầu

- Python 3.10 trở lên.
- API key cho ít nhất một provider nếu chạy chế độ LLM/hybrid: OpenAI, Gemini hoặc DashScope/Qwen.
- Nếu chạy model local cần thêm file model `.gguf` và cài `llama-cpp-python`.

## Cài đặt

Tạo và kích hoạt môi trường ảo trên Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Cài thư viện:

```powershell
pip install -r requirements.txt
```

Sao chép file cấu hình:

```powershell
Copy-Item .env.example .env
```

Mở `.env` và điền API key/provider muốn dùng.

Ví dụ chạy với OpenAI:

```env
OPENAI_API_KEY=your_openai_api_key_here
DEFAULT_PROVIDER=openai
DEFAULT_MODEL=gpt-4o
RETAIL_ADVISOR_MODE=hybrid
```

Ví dụ chạy với DashScope/Qwen:

```env
DASHSCOPE_API_KEY=your_dashscope_api_key_here
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
DEFAULT_PROVIDER=dashscope
DEFAULT_MODEL=qwen3-coder-flash
RETAIL_ADVISOR_MODE=hybrid
```

Nếu chỉ muốn chạy bằng luật cố định, không cần API key:

```env
RETAIL_ADVISOR_MODE=deterministic
```

## Cách chạy web app

Chạy server:

```powershell
python -m src.ui.server
```

Mở trình duyệt tại:

```text
http://127.0.0.1:8000
```

Trên giao diện web có thể:

- Nhập câu hỏi tư vấn tồn kho.
- Chọn danh mục sản phẩm.
- Chọn mùa vụ/kỳ bán hàng.
- Chọn chế độ phân tích `base`, `llm` hoặc `hybrid`.
- Xem kết quả, bảng sản phẩm đề xuất và trace các tool mà agent đã gọi.

## Chạy model local

Cài thêm thư viện local:

```powershell
pip install -r requirements-local.txt
```

Tải model `Phi-3-mini-4k-instruct-q4.gguf` từ Hugging Face:

```text
https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf
```

Tạo thư mục `models/` ở gốc dự án và đặt file model vào đó:

```text
models/Phi-3-mini-4k-instruct-q4.gguf
```

Cấu hình `.env`:

```env
DEFAULT_PROVIDER=local
LOCAL_MODEL_PATH=./models/Phi-3-mini-4k-instruct-q4.gguf
RETAIL_ADVISOR_MODE=hybrid
```

Sau đó chạy lại server:

```powershell
python -m src.ui.server
```

## Chạy test

Chạy toàn bộ test:

```powershell
pytest
```

Chạy một nhóm test cụ thể:

```powershell
pytest tests/test_retail_tools.py
pytest tests/test_react_agent.py
pytest tests/test_hybrid_advisor.py
```

## Cấu hình quan trọng trong `.env`

| Biến | Ý nghĩa |
| --- | --- |
| `DEFAULT_PROVIDER` | Provider LLM: `openai`, `google`, `gemini`, `dashscope`, `qwen`, `local` |
| `DEFAULT_MODEL` | Tên model dùng cho provider |
| `RETAIL_ADVISOR_MODE` | Chế độ mặc định: `hybrid` hoặc `deterministic` |
| `AI_MAX_STEPS` | Số vòng Thought/Action/Observation tối đa |
| `AI_TIMEOUT_SECONDS` | Thời gian tối đa cho LLM trước khi báo lỗi/fallback |
| `LOG_LEVEL` | Mức log |
| `LOCAL_MODEL_PATH` | Đường dẫn model `.gguf` khi dùng `DEFAULT_PROVIDER=local` |

## Luồng hoạt động chính

1. Người dùng gửi câu hỏi từ web UI.
2. `src/ui/server.py` nhận request và gọi `HybridRetailStockAdvisor`.
3. Advisor chọn chế độ `base`, `llm` hoặc `hybrid`.
4. Với chế độ LLM, `ReActAgent` gọi các tool trong `src/retail/tools.py`.
5. Tool đọc dữ liệu JSON qua repository và trả Observation.
6. Agent tổng hợp Final Answer bằng tiếng Việt.
7. UI hiển thị câu trả lời, bảng đề xuất, metrics và trace.
