> [!WARNING]
> **SUPERSEDED DOCUMENT**
> This initial MVP draft has been superseded by the updated technical documentation suite:
> - Product overview, current status, setup: [README.md](../README.md)
> - Technical architecture, schemas, and API: [docs/ARCHITECTURE.md](ARCHITECTURE.md)
> - Voice pipeline, extraction, and evaluation: [docs/AI_PIPELINE.md](AI_PIPELINE.md)
> - Verified status, gaps, and roadmap milestones: [docs/ROADMAP.md](ROADMAP.md)

# PRD — Personal Knowledge Capture & Recall (MVP) [Historical Reference]

Version 0.2 · Flutter · Mobile app · Researcher / Research Student

## 1. Mục tiêu

Xây dựng một mobile app tối giản giúp researcher ghi lại ý tưởng, dùng AI xử lý thành thông tin có cấu trúc, tìm lại bằng ngôn ngữ tự nhiên và tự quản lý bộ nhớ.

Ưu tiên cao nhất: App chạy được, build thành công và hoàn thành được flow end-to-end. Chưa cần tối ưu bảo mật hay xây kiến trúc phức tạp.

## 2. Core flow

1\. CAPTURE

Ghi âm hoặc nhập văn bản; lưu bản gốc

2\. PROCESS

API AI chuyển audio thành text (nếu cần), tạo tiêu đề, tóm tắt, ý tưởng và câu hỏi mở

3\. RECALL

Tìm ghi chú bằng câu hỏi tự nhiên, trả về kết quả liên quan và bản gốc

4\. MEMORY CONTROL

Xem, sửa và xóa ghi chú; phân biệt bản gốc với nội dung AI xử lý

## 3. Phạm vi tối thiểu

- Capture: Text input, ghi âm, lưu dữ liệu.
- Process: Tích hợp API model; tạo transcript và nội dung có cấu trúc.
- Recall: Semantic search trên các ghi chú đã lưu; có thể kết hợp tìm kiếm từ khóa.
- Memory control: Danh sách ghi chú, xem chi tiết, sửa, xóa.
- UI: Giao diện mobile đơn giản, đủ để kiểm thử toàn bộ flow.

Chưa làm: knowledge graph trực quan, agent, đồng bộ đa thiết bị, tích hợp Zotero, đăng nhập phức tạp, chia sẻ nhóm, analytics và tối ưu bảo mật nâng cao.

## 4. Kiến trúc tối thiểu

- Mobile: Flutter + Dart.
- Local storage: SQLite để lưu ghi chú và bản gốc.
- AI: API model cho speech-to-text, refinement và embedding.
- Backend: Chỉ thêm khi cần cho retrieval hoặc để giữ API key khỏi ứng dụng. Nếu có backend, dùng một service đơn giản, không cần microservices.
- Retrieval: Embedding + vector search; có thể dùng backend và vector database nhẹ. Nếu cần build prototype nhanh, bắt đầu bằng tìm kiếm từ khóa rồi bổ sung semantic search.
- Data model: `Note(id, originalContent, transcript, summary, structuredData, createdAt, updatedAt)`.

Lưu ý: API key không nên hardcode vào bản app phân phối. Trong giai đoạn prototype, có thể dùng backend proxy tối giản.

## 5. Acceptance criteria

MVP đạt yêu cầu khi:

- Flutter app chạy được trên thiết bị hoặc emulator mục tiêu.
- Build thành công theo hướng dẫn trong repository.
- Ghi âm hoặc nhập text và lưu được ghi chú.
- AI xử lý ghi chú thành công; lỗi xử lý không làm mất bản gốc.
- Tìm lại được ghi chú bằng truy vấn tự nhiên.
- Xem, sửa và xóa ghi chú được.
- Hoàn thành flow CAPTURE → PROCESS → RECALL → MEMORY CONTROL.
- Có README hướng dẫn cấu hình API, chạy và build app.

## 6. Thứ tự triển khai

1. Khởi tạo Flutter app và xác nhận build thành công.
2. Xây capture + SQLite.
3. Tích hợp API AI và process.
4. Xây recall.
5. Hoàn thiện memory control.
6. Chạy thử end-to-end, sửa lỗi và viết README.

Nguyên tắc: Không over-engineer. Ưu tiên một ứng dụng chạy được với flow hoàn chỉnh; chỉ mở rộng kiến trúc khi có nhu cầu thực tế.