# Hướng Dẫn Triển Khai Gusby Trên Linux VPS (Deployment Guide)

Tài liệu hướng dẫn chi tiết quy trình chuẩn bị, cài đặt, cấu hình và vận hành nền tảng Gusby Knowledge Graph trên một máy chủ riêng ảo (VPS) chạy hệ điều hành Linux tiêu chuẩn (Debian, Ubuntu, AlmaLinux, Fedora).

---

## 1. Kiến Trúc Triển Khai (Deployment Architecture)

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'background': 'transparent', 'clusterBkg': 'none' }}}%%
flowchart TD
    subgraph ClientEcosystem ["Môi Trường Truy Cập"]
        UserBrowser["Trình Duyệt Người Dùng (Client)"]
    end

    subgraph EdgeNetwork ["Cổng Biên & Bảo Mật"]
        CFTunnel["Cloudflare Tunnel / Tên Miền Công Cộng"]
        NginxServer["Nginx Web Server (:8080)"]
    end

    subgraph InternalApp ["Ứng Dụng Gusby (Quản Lý Bởi PM2)"]
        StaticFrontend["Frontend Static SPA Files\n(/frontend/.output/public)"]
        GoBackend["Go Backend API & Job Queue Worker\n(127.0.0.1:8081 - Không Mở Public)"]
    end

    subgraph DataPersistence ["Lưu Trữ Dữ Liệu"]
        PostgresDB["PostgreSQL (127.0.0.1:5432)\nDatabase: gusby_db | Schema: gusby"]
    end

    UserBrowser -->|HTTPS| CFTunnel
    CFTunnel -->|HTTP| NginxServer
    NginxServer -->|/api/*| GoBackend
    NginxServer -->|/* (Static Assets)| StaticFrontend
    GoBackend -->|pgx pool| PostgresDB
```

**Nguyên tắc cốt lõi:**
- Nginx lắng nghe tại cổng `8080`, phục vụ trực tiếp file tĩnh của giao diện Nuxt SPA và làm reverse proxy chuyển tiếp các yêu cầu bắt đầu bằng `/api/` tới Go Backend trên cổng `127.0.0.1:8081`.
- Go Backend và PostgreSQL chạy hoàn toàn ở chế độ riêng tư (chỉ bind trên `127.0.0.1`), tuyệt đối không mở port `8081` hoặc `5432` ra mạng công cộng.

---

## 2. Yêu Cầu Phần Cứng & Hệ Điều Hành

- **Hệ điều hành**: Linux x86_64 hoặc ARM64 (Debian 12+, Ubuntu 22.04 LTS+, Fedora 39+, Rocky/AlmaLinux 9+).
- **RAM**: Tối thiểu 1 GB RAM (Khuyến nghị 2 GB trở lên).
- **CPU**: Tối thiểu 1 vCPU (Khuyến nghị 2 vCPU).
- **Ổ cứng**: Tối thiểu 10 GB SSD trống cho hệ điều hành, cơ sở dữ liệu và file biên dịch.

---

## 3. Phiên Bản Phần Mềm Hỗ Trợ

- **Go**: 1.23+ (Đã kiểm thử hoạt động ổn định trên Go 1.27.3).
- **Node.js**: 18.x LTS, 20.x LTS hoặc 22.x LTS (Đã kiểm thử trên Node 20+).
- **PostgreSQL**: 16.x, 17.x hoặc 18.x (Đã kiểm thử tương thích hoàn toàn với PostgreSQL 18.6).
- **Nginx**: 1.20+ hoặc mới hơn.
- **PM2**: 5.x+ (Cài đặt qua `npm install -g pm2`).

---

## 4. Cài Đặt Các Gói Phụ Thuộc (Prerequisites)

### Trên Ubuntu / Debian:

```bash
sudo apt-get update
sudo apt-get install -y git curl build-essential nginx postgresql postgresql-contrib

# Cài đặt Node.js LTS (nếu chưa có)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Cài đặt PM2 toàn cục
sudo npm install -g pm2

# Cài đặt Go (hoặc tải từ trang chủ golang.org)
sudo apt-get install -y golang
```

---

## 5. Tải Mã Nguồn Ứng Dụng (Repository Checkout)

```bash
cd /var/www  # hoặc thư mục triển khai mong muốn của bạn
git clone https://github.com/FatPandaC8/KBA.git gusby
cd gusby
```

---

## 6. Cấu Hình Biến Môi Trường (Environment Configuration)

Tạo file `.env` từ file mẫu:

```bash
cp .env.example .env
```

Mở file `.env` và chỉnh sửa các tham số sản xuất:

```ini
GUSBY_ENV=production
GUSBY_HOST=127.0.0.1
GUSBY_PORT=8081

# Chuỗi kết nối database với user và db riêng biệt
GUSBY_DATABASE_URL=postgresql://gusby_user:YOUR_SECURE_PASSWORD@127.0.0.1:5432/gusby_db

# Tạo chuỗi bí mật tối thiểu 32 ký tự bằng lệnh: openssl rand -base64 32
GUSBY_SESSION_SECRET=YOUR_GENERATED_32_CHAR_SECRET_KEY

# Khóa API Groq Cloud
GROQ_API_KEY=gsk_your_actual_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b

# Cấu hình Frontend
GUSBY_API_BASE=
E2E_SEED_ENABLED=false
```

---

## 7. Khởi Tạo Cơ Sở Dữ Liệu & Phân Quyền Tối Thiểu (Least-Privilege Role)

Gusby sử dụng database riêng và schema riêng biệt `gusby`, giúp cách ly hoàn toàn dữ liệu với các cơ sở dữ liệu khác đang chạy trên cùng server (ví dụ database `server_lab`).

Đăng nhập vào PostgreSQL với quyền admin (postgres):

```bash
sudo -u postgres psql
```

Chạy đoạn mã SQL sau để tạo database, tài khoản và phân quyền:

```sql
-- 1. Tạo database riêng cho Gusby
CREATE DATABASE gusby_db;

-- 2. Kết nối vào database vừa tạo
\c gusby_db

-- 3. Kích hoạt extension bắt buộc pg_trgm
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 4. Tạo người dùng ứng dụng không có quyền superuser
CREATE USER gusby_user WITH ENCRYPTED PASSWORD 'YOUR_SECURE_PASSWORD';

-- 5. Cấp quyền truy cập kết nối vào database
GRANT CONNECT ON DATABASE gusby_db TO gusby_user;

-- 6. Tạo schema chuyên dụng và gán quyền sở hữu
CREATE SCHEMA IF NOT EXISTS gusby AUTHORIZATION gusby_user;
GRANT ALL PRIVILEGES ON SCHEMA gusby TO gusby_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA gusby TO gusby_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA gusby TO gusby_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA gusby GRANT ALL ON TABLES TO gusby_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA gusby GRANT ALL ON SEQUENCES TO gusby_user;

-- 7. Bảo vệ database khác (nếu có): Thu hồi mọi quyền của gusby_user trên database khác
REVOKE ALL ON DATABASE server_lab FROM gusby_user;
```

---

## 8. Chạy Migration Cơ Sở Dữ Liệu

Thực thi script di trú schema tự động:

```bash
chmod +x ./scripts/migrate.sh
./scripts/migrate.sh
```

Script sẽ áp dụng lần lượt:
1. `migrations/gusby/0001_initial_schema.sql` (21 bảng khởi tạo, chỉ mục trigram, quan hệ khoá ngoại).
2. `migrations/gusby/0002_admin_and_ai_observability.sql` (bảng giám sát AI, audit log, admin flags).

---

## 9. Biên Dịch Backend (Go Binary Build)

Biên dịch ứng dụng Go thành một file thực thi nhị phân độc lập không phụ thuộc cgo:

```bash
CGO_ENABLED=0 go build -ldflags="-s -w" -o ./bin/gusby ./cmd/gusby
```

Kiểm tra file thực thi:

```bash
./bin/gusby admin list
```

---

## 10. Biên Dịch Frontend (Nuxt Static SPA Generation)

Frontend được cấu hình ở chế độ `ssr: false`. Do đó, sử dụng lệnh `generate` để xuất toàn bộ giao diện thành các file tĩnh HTML/CSS/JS thuần túy:

```bash
cd frontend
npm ci
npm run generate
cd ..
```

Toàn bộ file tĩnh được tạo ra tại thư mục `frontend/.output/public`.

---

## 11. Cấu Hình PM2 (Process Management)

Gusby sử dụng PM2 để duy trì tiến trình Go backend chạy liên tục trong nền, tự động khởi động lại khi crash hoặc khi đạt giới hạn bộ nhớ:

Tạo thư mục log nếu chưa có:

```bash
mkdir -p logs
```

Khởi động ứng dụng bằng file `ecosystem.config.cjs`:

```bash
pm2 start ecosystem.config.cjs
pm2 save
```

Cấu hình PM2 tự khởi động khi máy chủ reboot:

```bash
pm2 startup
```

---

## 12. Cấu Hình Nginx Reverse Proxy

Sao chép file cấu hình mẫu vào Nginx:

```bash
sudo cp deploy/nginx/gusby-linux.conf /etc/nginx/conf.d/gusby.conf
```

Mở file `/etc/nginx/conf.d/gusby.conf` và kiểm tra đường dẫn `root` khớp với vị trí đặt source code của bạn (ví dụ: `/var/www/gusby/frontend/.output/public`).

Kiểm tra cú pháp Nginx và nạp lại cấu hình:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

---

## 13. Kiểm Tra Sức Khỏe Dịch Vụ (Health Checks)

Sau khi khởi động Nginx và PM2, kiểm tra trạng thái hoạt động:

```bash
# 1. Kiểm tra Liveness (Trạng thái sống của HTTP server)
curl -i http://127.0.0.1:8080/api/health

# 2. Kiểm tra Readiness (Kiểm tra kết nối PostgreSQL và AI Gate)
curl -i http://127.0.0.1:8080/api/health/ready
```

Kết quả phản hồi chuẩn của `/api/health/ready`:

```json
{
  "ai_gate": "enabled",
  "ai_provider": "groq",
  "database": "connected",
  "service": "gusby",
  "status": "ready",
  "version": "1.0.0"
}
```

---

## 14. Kiểm Tra Log Ứng Dụng

- Log Go Backend: `tail -f logs/backend-out.log`
- Log Lỗi Go Backend: `tail -f logs/backend-err.log`
- Log Nginx truy cập: `sudo tail -f /var/log/nginx/access.log`
- Log Nginx lỗi: `sudo tail -f /var/log/nginx/error.log`
- Log PM2 tổng hợp: `pm2 logs gusby-backend`

---

## 15. Quy Trình Khởi Động Lại & Tắt Ứng Dụng

- **Khởi động lại toàn bộ**:
  ```bash
  pm2 restart gusby-backend
  sudo systemctl reload nginx
  ```
- **Tắt ứng dụng**:
  ```bash
  pm2 stop gusby-backend
  ```

---

## 16. Quy Trình Cập Nhật Phiên Bản Mới (Update via Git)

Khi có bản cập nhật mới trên GitHub:

```bash
# 1. Kéo mã nguồn mới nhất
git pull origin main

# 2. Cập nhật migration database (nếu có file SQL mới)
./scripts/migrate.sh

# 3. Biên dịch lại backend
CGO_ENABLED=0 go build -ldflags="-s -w" -o ./bin/gusby ./cmd/gusby

# 4. Biên dịch lại frontend
cd frontend
npm ci
npm run generate
cd ..

# 5. Khởi động lại ứng dụng không gián đoạn
pm2 reload gusby-backend
sudo systemctl reload nginx
```

---

## 17. Sao Lưu Dữ Liệu (Backup Procedure)

Sao lưu định kỳ cơ sở dữ liệu `gusby_db`:

```bash
mkdir -p /var/backups/gusby
BACKUP_FILE="/var/backups/gusby/gusby_db_$(date +%Y%m%d_%H%M%S).sql.gz"

pg_dump -h 127.0.0.1 -U gusby_user -d gusby_db | gzip > "$BACKUP_FILE"
echo "Backup created at: $BACKUP_FILE"
```

---

## 18. Phục Hồi Dữ Liệu (Restore Procedure)

Khi cần khôi phục lại trạng thái dữ liệu từ file backup:

```bash
# 1. Tạm dừng backend để tránh ghi đè đồng thời
pm2 stop gusby-backend

# 2. Xả nén và nạp dữ liệu vào PostgreSQL
gunzip -c /var/backups/gusby/YOUR_BACKUP_FILE.sql.gz | psql -h 127.0.0.1 -U gusby_user -d gusby_db

# 3. Khởi động lại backend
pm2 start gusby-backend
```

---

## 19. Quy Trình Rollback Khi Gặp Lỗi

Nếu bản build mới gặp sự cố:

1. Rollback mã nguồn Git: `git checkout <COMMIT_HASH_TRUOC>`
2. Biên dịch lại nhị phân: `go build -o ./bin/gusby ./cmd/gusby`
3. Xuất lại frontend: `cd frontend && npm run generate && cd ..`
4. Khởi động lại dịch vụ: `pm2 restart gusby-backend`
5. Khôi phục lại bản backup database gần nhất nếu có thay đổi schema không tương thích.

---

## 20. Khắc Phục Sự Cố Phổ Biến (Troubleshooting)

| Hiện Tượng | Nguyên Nhân Khả Dĩ | Cách Xử Lý |
|---|---|---|
| Gọi `/api/health/ready` trả về HTTP 503 | PostgreSQL chưa chạy hoặc sai mật khẩu trong `.env` | Kiểm tra service: `sudo systemctl status postgresql`. Xác minh lại chuỗi kết nối `GUSBY_DATABASE_URL`. |
| Nginx trả về lỗi 502 Bad Gateway | Go Backend chưa chạy trên cổng 8081 | Kiểm tra trạng thái PM2: `pm2 status`. Xem file log lỗi: `tail -n 50 logs/backend-err.log`. |
| Giao diện tải được nhưng API báo 403 Forbidden | CSRF Origin không khớp | Thêm tên miền truy cập vào biến `GUSBY_CORS_ALLOWED_ORIGINS` trong file `.env`. |
| Backend báo lỗi không tìm thấy `pg_trgm` | Extension trigram chưa được tạo trong database | Đăng nhập database với quyền superuser và chạy: `CREATE EXTENSION pg_trgm;` |
