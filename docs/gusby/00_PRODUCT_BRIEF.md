# TÀI LIỆU YÊU CẦU SẢN PHẨM: GUSBY (PRODUCT BRIEF)
*Ngôn ngữ gốc: Tiếng Việt | Trạng thái: Decided & Canonical*

---

## 1. Tầm Nhìn & Định Vị Cốt Lõi

**Gusby** là một nền tảng Web Text-to-Knowledge-Graph (từ văn bản sang đồ thị tri thức), có nhiệm vụ chuyển hoá văn bản tự do, đường dẫn web (URL) và tệp tài liệu thành tri thức có cấu trúc, liên kết chặt chẽ và tuyệt đối đáng tin cậy.

### Triết Lý Nền Tảng: Precision Over Recall (Chính Xác Vượt Trên Độ Phủ)
- **Một đồ thị nhỏ nhưng đúng 100% có giá trị gấp nhiều lần một đồ thị khổng lồ nhưng chứa các liên kết sai lệch, suy diễn vô căn cứ.**
- Mọi mối quan hệ (relationship/edge) giữa các khái niệm (concept/node) trong Gusby **bắt buộc phải giải thích được bằng trích dẫn bằng chứng nguyên văn (exact verbatim evidence)** từ tài liệu nguồn gốc.
- Không bao giờ chấp nhận ảo giác (hallucination) hay suy đoán của mô hình AI khi không có bằng chứng văn bản cụ thể.

---

## 2. Các Luồng Đầu Vào (Inputs) & Vòng Đời Xử Lý

### 2.1. Nguồn Dữ Liệu Đầu Vào Hỗ Trợ trong MVP
1. **Văn bản thuần (Raw Text)**: Nhập trực tiếp qua khung văn bản.
2. **Đường dẫn Web (URL)**: Trích xuất nội dung bài viết/trang web an toàn (chống SSRF).
3. **Tệp tài liệu (Files)**: Hỗ trợ tệp định dạng `.txt`, `.pdf` (có lớp văn bản số, không hỗ trợ PDF scan thuần ảnh trong MVP), `.docx`.

### 2.2. Trạng Thái Tài Liệu (Document Statuses)
- `Uploading`: Đang tiếp nhận dữ liệu từ người dùng.
- `Processing`: Đang trong tiến trình bóc tách, trích xuất thực thể, đối soát bằng chứng và tích hợp.
- `Completed`: Đã xử lý thành công, tích hợp vào đồ thị tri thức.
- `Failed`: Thất bại trong quá trình bóc tách (kèm thông báo nguyên nhân cụ thể, không che giấu lỗi).

### 2.3. Hỗ Trợ Đa Ngôn Ngữ & An Toàn Unicode
- Xử lý mượt mà và bình đẳng giữa Tiếng Việt (bao gồm toàn bộ dấu thanh phức hợp và ký tự ghép) và Tiếng Anh.
- Quy chuẩn mã hoá UTF-8 chuẩn xác từ khâu tính toán toạ độ chuỗi (offsets) ở backend tới hiển thị highlight ở frontend.

---

## 3. Mô Hình Dữ Liệu Tri Thức (Knowledge Model)

Hệ thống được xây dựng trên các thực thể nền tảng:

1. **Document (Tài liệu nguồn)**:
   - Lưu trữ văn bản gốc bất biến (immutable source text) và hàm băm nội dung (content hash) để chống trùng lặp.
   - Mỗi Document sở hữu một **Document Graph** riêng biệt: thể hiện chính xác những gì Gusby hiểu được từ riêng tài liệu đó. Document Graph này được lưu giữ vĩnh viễn và không bị biến dạng ngay cả khi các khái niệm được hợp nhất (merged) ở đồ thị hợp nhất chung.
2. **Concept (Khái niệm)**:
   - Là các **nút (nodes)** duy nhất trên đồ thị tri thức. Đại diện cho thực thể, thuật ngữ hoặc ý niệm cốt lõi.
   - Sở hữu danh sách định danh bí danh (aliases) để hỗ trợ quá trình hợp nhất thực thể.
3. **Proposition (Mệnh đề / Mối quan hệ)**:
   - Là các **cạnh có hướng (directed edges)** kết nối từ Khái niệm Chủ thể (Subject Concept) tới Khái niệm Khách thể (Object Concept) với một vị từ (Predicate).
4. **Evidence (Bằng chứng trích dẫn)**:
   - Đoạn trích dẫn nguyên văn (verbatim text span) từ tài liệu gốc chứng minh cho sự tồn tại của Mệnh đề.
   - Đi kèm toạ độ đoạn trích (start offset, end offset) chuẩn xác.
5. **Knowledge Graph (Canonical Graph)**:
   - Đồ thị tri thức hợp nhất toàn cục của mỗi người dùng (độc lập tuyệt đối giữa các người dùng).
6. **Topic (Chủ đề)**:
   - Lớp phân nhóm tri thức trực giao (orthogonal organizational layer).
   - Quan hệ nhiều-nhiều (many-to-many) với Concept.
   - Không phân cấp (no nested hierarchy), không làm thay đổi bản sắc của Concept hay Proposition.

---

## 4. Cơ Chế Tích Hợp Tri Thức & 4 Chiều Độc Lập Về Độ Tin Cậy

Hệ thống tuyệt đối **không gộp chung (collapse)** các thước đo độ tin cậy thành một con số duy nhất. Quá trình tích hợp vào Canonical Graph xem xét 4 chiều độc lập:
1. **Extraction Confidence**: Độ tin cậy trong bước trích xuất của LLM.
2. **Evidence Validity**: Tính hợp lệ tuyệt đối của bằng chứng (phải tìm thấy nguyên văn trong văn bản gốc thông qua thuật toán xác minh xác định của Go).
3. **Entity Resolution Confidence**: Độ tin cậy khi liên kết Concept trích xuất với Concept đã tồn tại trong đồ thị.
4. **Proposition Confidence**: Độ tin cậy về ngữ nghĩa của mối quan hệ giữa hai Concept.

### Chính Sách Tích Hợp:
- **Độ tin cậy Cao (High)**: Tự động tích hợp vào Canonical Graph.
- **Độ tin cậy Vừa (Medium)**: Tạo đề xuất tích hợp (Integration Proposal) và gắn cờ `needs_review = true`.
- **Độ tin cậy Thấp (Low)**: Giữ nguyên trong Document Graph cục bộ, không đưa vào Canonical Graph.
- **Bằng chứng Không hợp lệ hoặc Thiếu**: Tuyệt đối **không bao giờ** được tích hợp vào Canonical Graph.

---

## 5. Xử Lý Xung Đột Tri Thức (Conflict Handling)

Gusby coi xung đột tri thức là điều bình thường trong thực tế:
- Khi phát hiện mệnh đề mới có cùng Subject và Predicate nhưng mâu thuẫn về Object, thời gian, điều kiện hoặc phạm vi:
  - **Không bao giờ ghi đè hoặc tự ý xoá bỏ thông tin cũ**.
  - Lưu giữ cả hai mệnh đề cùng với đầy đủ bằng chứng đối chiếu của từng bên.
  - Phân loại xung đột: (1) Khác biệt ngữ cảnh (Contextual difference), (2) Mâu thuẫn trực tiếp (Contradiction), (3) Thiếu bằng chứng kết luận (Insufficient evidence).
  - Tự động bổ sung ngữ cảnh nếu có đủ căn cứ rõ ràng; nếu là mâu thuẫn thực sự, đánh dấu trạng thái xung đột (`conflict`) để người dùng xem xét.
  - Lưu lại nhật ký kiểm toán (audit log) ghi rõ ai hoặc cơ chế nào đưa ra quyết định (AI hay User) và lý do cụ thể.

---

## 6. Triết Lý Trải Nghiệm: Review Là Trạng Thái, Không Phải Một Trang

- **Không xây dựng trang "Review Queue" độc lập**.
- Mọi mục cần người dùng can thiệp (đề xuất tích hợp trung bình, xung đột mệnh đề, hợp nhất thực thể mập mờ) đều được hiển thị trực tiếp dưới dạng **trạng thái đánh dấu (flagged review state)** trên các nút và cạnh trong Knowledge Space và bảng điều khiển cạnh (side panel).
- Người dùng có thể lọc nhanh các mục này bằng bộ lọc `[Needs Review]` ngay trên không gian đồ thị.

---

## 7. Kiến Trúc Giao Diện & Trải Nghiệm Người Dùng (Desktop-First)

### 7.1. Knowledge Space (Không Gian Tri Thức Trung Tâm)
- Thiết kế dạng **Topic Islands** (các đảo chủ đề phân bổ tự nhiên).
- **Semantic Zoom (Thu phóng ngữ nghĩa 4 cấp độ)**:
  - **Mức Xa (Far)**: Hiển thị các Đảo Chủ đề (Topics).
  - **Mức Gần Hơn (Closer)**: Hiển thị các Khái niệm Cốt lõi (Main Concepts).
  - **Mức Chi Tiết (Deep)**: Hiển thị toàn bộ Khái niệm và các mối quan hệ liên kết (Concepts & Relations).
  - **Mức Sâu Nhất (Deepest)**: Hiển thị chi tiết các Mệnh đề và trích dẫn bằng chứng (Propositions & Evidence).
- Nút đồ thị dạng hình tròn tối giản, thanh mảnh, màu sắc phân biệt theo bảng màu tự nhiên (earthy preset palettes).
- Nhấp vào Chủ đề để chuyển camera phóng cận cảnh vào Đảo Chủ đề đó; nhấp vào Khái niệm để mở popover nhanh, mở rộng thành bảng cạnh (side panel) hiển thị nguồn gốc và ngữ cảnh trích dẫn nguyên văn.
- Thanh tìm kiếm nổi (floating search bar) tìm kiếm nhanh và làm nổi bật các nút kết quả trên đồ thị.
- Backend cung cấp dữ liệu đồ thị theo từng mức độ chi tiết (Level-of-Detail Projections) với giới hạn nút nghiêm ngặt để đảm bảo tốc độ phản hồi 60fps mượt mà.

### 7.2. Add Knowledge (Khu Vực Nạp Tri Thức)
- Giao diện nạp tri thức tập trung, hỗ trợ kéo thả tệp, nhập văn bản hoặc dán đường dẫn URL.

### 7.3. Documents (Kho Tài Liệu)
- Danh sách tài liệu tối giản: hiển thị tên tài liệu, loại nguồn, ngày thêm, số lượng thực thể bóc tách và trạng thái xử lý.

### 7.4. Settings & Auth
- Cài đặt tài khoản tối giản: chọn bảng màu hiển thị (earthy palettes), đổi mật khẩu, đăng xuất.
- Đăng ký và đăng nhập bảo mật qua Email + Mật khẩu.

---

## 8. Những Tính Năng Nằm Ngoài Phạm Vi MVP (Explicit Out-of-Scope)
- Ứng dụng di động (Mobile App) — Chỉ tập trung Desktop Web.
- Xử lý âm thanh/giọng nói (Audio/Speech/STT) — Đã có trong Echo, không đưa vào Gusby.
- Nhắc nhở, quản lý công việc (Tasks/Reminders).
- Trợ lý trò chuyện phiếm chung (General Chatbot).
- Trình soạn thảo ghi chú dạng Notion/Obsidian.
- Tính năng làm việc nhóm, chia sẻ công khai, phân quyền doanh nghiệp (Collaboration/Enterprise).
- Chế độ nền tối (Dark Mode) — Thiết kế chuẩn mực nền trắng tinh khiết (Light mode only).
- Chủ đề lồng nhau (Nested Topics).
- Chỉnh sửa cấu trúc đồ thị vẽ tay tự do (Manual freehand graph editing).
