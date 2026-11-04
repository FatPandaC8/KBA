# Tài Liệu Tham Chiếu Biến Môi Trường Gusby (Environment Reference)

Tài liệu này liệt kê toàn bộ các biến môi trường được backend Go và frontend Nuxt sử dụng trong mã nguồn thực tế của Gusby.

---

## 1. Bảng Biến Môi Trường Backend (Go API & Queue Worker)

| Biến Môi Trường | Bắt Buộc (Production) | Giá Trị Mặc Định | Mô Tả Chi Tiết |
|---|---|---|---|
| `GUSBY_ENV` | Không | `development` | Môi trường thực thi (`development`, `production`, `test`). Khi đặt `production`, hệ thống kích hoạt xác thực bảo mật nghiêm ngặt. |
| `GUSBY_HOST` | Không | `127.0.0.1` | Địa chỉ IP loopback mà HTTP server lắng nghe. Giữ nguyên `127.0.0.1` để tránh mở trực tiếp backend ra internet. |
| `HOST` | Không | `127.0.0.1` | Biến dự phòng cho `GUSBY_HOST`. |
| `GUSBY_PORT` | Không | `8081` | Cổng mạng của Go backend HTTP API. Mặc định là `8081` để nhường cổng `8080` cho Nginx reverse proxy. |
| `PORT` | Không | `8081` | Biến dự phòng cho `GUSBY_PORT`. |
| `GUSBY_DATABASE_URL` | Có (Prod) | Fallback dev: `postgresql://echo:...` | Chuỗi kết nối PostgreSQL. Trong production bắt buộc phải khai báo URL riêng (ví dụ: `postgresql://gusby_user:matkhau@127.0.0.1:5432/gusby_db`). |
| `DATABASE_URL` | Không | Trùng `GUSBY_DATABASE_URL` | Biến dự phòng chuẩn cho chuỗi kết nối PostgreSQL. |
| `GUSBY_SESSION_SECRET` | Có (Prod) | Insecure dev key | Chuỗi khóa bí mật dùng để mã hóa và ký cookie phiên đăng nhập. Trong production bắt buộc phải có độ dài tối thiểu 32 ký tự ngẫu nhiên. |
| `GUSBY_CORS_ALLOWED_ORIGINS` | Không | Loopback ports: 3000, 8080, 8081 | Danh sách các Origin được phép truy cập CORS và CSRF, phân tách bằng dấu phẩy (ví dụ: `https://gusby.example.com,http://127.0.0.1:8080`). |
| `GUSBY_OWNER_EMAIL` | Không | Rỗng | Email của chủ sở hữu hệ thống. Khi khởi động, tài khoản này sẽ tự động được gán quyền Admin cao nhất (`is_admin = true`). |
| `GROQ_API_KEY` | Có (Prod) | Rỗng (Dùng mock LLM ở dev) | Khóa API Groq Cloud dùng để trích xuất tri thức, phân giải thực thể và phân loại mâu thuẫn. |
| `GROQ_MODEL` | Không | `openai/gpt-oss-120b` | Tên mô hình LLM trên Groq (hoặc mô hình tương thích OpenAI endpoint). |
| `GROQ_BASE_URL` | Không | `https://api.groq.com/openai/v1` | URL gốc của Groq API hoặc server inference tự host tương thích OpenAI. |
| `GROQ_RPM` | Không | `30` | Hạn mức số lượng request mỗi phút (Requests Per Minute) của tài khoản Groq. |
| `GROQ_TPM` | Không | `8000` | Hạn mức số lượng token mỗi phút (Tokens Per Minute) của tài khoản Groq. |
| `GUSBY_DAILY_USER_TOKEN_BUDGET` | Không | `40000` | Hạn mức ngân sách token tối đa mà một người dùng bình thường được tiêu thụ trong một ngày dương lịch. |
| `E2E_SEED_ENABLED` | Không | `false` | Cờ tự động tạo các tài khoản mẫu kiểm thử khi khởi động. **Bắt buộc tắt (`false`) trong production**. |
| `E2E_ADMIN_EMAIL` | Không | Rỗng | Email tài khoản admin mẫu khi seed. |
| `E2E_ADMIN_PASSWORD` | Không | Rỗng | Mật khẩu tài khoản admin mẫu khi seed. |

---

## 2. Bảng Biến Môi Trường Frontend (Nuxt SPA Client)

| Biến Môi Trường | Bắt Buộc (Production) | Giá Trị Mặc Định | Mô Tả Chi Tiết |
|---|---|---|---|
| `GUSBY_API_BASE` | Không | Rỗng (`""`) | URL tiền tố cho các API request từ trình duyệt. Trong mô hình Nginx reverse proxy, để rỗng để trình duyệt gọi relative path `/api/...` cùng origin. |
| `GUSBY_BACKEND_URL` | Không | `http://127.0.0.1:8081` | Địa chỉ backend đích khi chạy Nuxt dev server (`npm run dev`) để reverse proxy cục bộ sang Go backend. |

---

## 3. Tạo Khóa Bí Mật Cho Production

Để tạo giá trị cho `GUSBY_SESSION_SECRET`, chạy lệnh sau trên terminal Linux hoặc Termux:

```bash
openssl rand -base64 32
```

Sao chép chuỗi kết quả và dán vào file `.env` trên VPS.
