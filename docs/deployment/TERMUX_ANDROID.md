# Hướng Dẫn Triển Khai Gusby Trên Android Termux ARM64 (VPS Lab)

Tài liệu hướng dẫn triển khai nền tảng Gusby Knowledge Graph trực tiếp trên thiết bị Android chạy Termux kiến trúc ARM64 không root.

---

## 1. Đặc Điểm Môi Trường Android Termux ARM64

| Yếu Tố | Môi Trường Linux VPS Tiêu Chuẩn | Môi Trường Android Termux |
|---|---|---|
| **Quyền Quản Trị** | Root (`sudo`) | User không root (`u0_a...`) |
| **Hệ Quản Lý Dịch Vụ** | `systemd` / `init` | Không có systemd; dùng `pg_ctl`, `pm2`, `termux-services` |
| **Đường Dẫn Gốc Thư Viện** | `/usr`, `/etc`, `/var` | `$PREFIX` (`/data/data/com.termux/files/usr`) |
| **Đường Dẫn Người Dùng** | `/home/<user>` | `$HOME` (`/data/data/com.termux/files/home`) |
| **Hệ Quản Lý Gói** | `apt`, `dnf`, `pacman` | `pkg` hoặc `apt` của Termux |
| **Tiến Trình Chạy Ngầm** | Vĩnh viễn qua daemon | Bị Android Doze & Battery Optimization giới hạn trừ khi giữ Wake Lock |

---

## 2. Kiến Trúc Luồng Truy Cập Trên Android VPS Lab

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'background': 'transparent', 'clusterBkg': 'none' }}}%%
flowchart TD
    subgraph InternetZone ["Mạng Internet Công Cộng"]
        RemoteUser["Trình Duyệt Người Dùng"]
    end

    subgraph TunnelEgress ["Đường Hầm Egress Bảo Mật"]
        CloudflareEdge["Cloudflare Edge (HTTPS)"]
        CFTunnel["cloudflared tunnel (Chạy trong Termux)"]
    end

    subgraph TermuxAndroid ["Thiết Bị Android Termux (ARM64)"]
        TermuxNginx["Nginx Reverse Proxy (:8080)"]
        GusbyApp["Go Backend API & Worker (:8081)\n(Quản Lý Bởi PM2)"]
        StaticPublic["Frontend Nuxt Static SPA\n($HOME/KBA/frontend/.output/public)"]
        TermuxPG["PostgreSQL 18.6 (:5432 - Loopback)\nDatabase: gusby_db | Schema: gusby"]
    end

    RemoteUser -->|HTTPS| CloudflareEdge
    CloudflareEdge -->|Encrypted Quic/HTTP2 Tunnel| CFTunnel
    CFTunnel -->|Forward HTTP| TermuxNginx
    TermuxNginx -->|/api/*| GusbyApp
    TermuxNginx -->|/* (Static)| StaticPublic
    GusbyApp --> TermuxPG
```

---

## 3. Cài Đặt Gói Cần Thiết Trên Termux

Mở ứng dụng Termux và chạy:

```bash
# 1. Cập nhật kho gói Termux
pkg update && pkg upgrade -y

# 2. Cài đặt các công cụ nền tảng
pkg install -y git golang nodejs-lts postgresql nginx openssl-tool curl

# 3. Cài đặt PM2 để quản lý tiến trình
npm install -g pm2
```

---

## 4. Cấu Hình Cơ Sở Dữ Liệu PostgreSQL Native Trên Termux

Trong Termux, PostgreSQL chạy hoàn toàn dưới quyền của user ứng dụng không root thông qua lệnh `pg_ctl`.

### 4.1. Khởi tạo cụm database (Nếu chưa có)

```bash
# Thư mục dữ liệu mặc định của Termux:
# $PREFIX/var/lib/postgresql
if [ ! -d "$PREFIX/var/lib/postgresql" ]; then
    initdb "$PREFIX/var/lib/postgresql"
fi
```

### 4.2. Khởi động PostgreSQL bằng `pg_ctl`

```bash
pg_ctl -D "$PREFIX/var/lib/postgresql" -l "$PREFIX/var/log/postgresql.log" start
```

Kiểm tra PostgreSQL đang chạy:

```bash
pg_ctl -D "$PREFIX/var/lib/postgresql" status
```

### 4.3. Tạo Database `gusby_db` & Cấu Hình Schema (Bảo Toàn `server_lab`)

Trên Termux, tài khoản mặc định chính là username Termux hiện tại của bạn (chạy lệnh `whoami` để xem).

Kết nối vào psql:

```bash
psql -d postgres
```

Thực thi SQL để tạo database riêng và kích hoạt `pg_trgm`:

```sql
-- 1. Tạo database riêng cho Gusby
CREATE DATABASE gusby_db;

-- 2. Kết nối vào gusby_db
\c gusby_db

-- 3. Cài đặt extension trigram
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 4. Tạo schema gusby
CREATE SCHEMA IF NOT EXISTS gusby;

-- Kiểm tra danh sách database (xác nhận server_lab không bị ảnh hưởng)
\l
\q
```

---

## 5. Tải Mã Nguồn & Cấu Hình Ứng Dụng

```bash
cd "$HOME"
git clone https://github.com/FatPandaC8/KBA.git
cd KBA

# Tạo file .env
cp .env.example .env
```

Chỉnh sửa file `.env`:

```ini
GUSBY_ENV=production
GUSBY_HOST=127.0.0.1
GUSBY_PORT=8081

# Lấy username hiện tại bằng lệnh `whoami`
# Chuỗi kết nối local PostgreSQL trên Termux:
GUSBY_DATABASE_URL=postgresql://$(whoami)@127.0.0.1:5432/gusby_db

# Tạo secret 32 ký tự bằng lệnh: openssl rand -base64 32
GUSBY_SESSION_SECRET=YOUR_RANDOM_32_CHAR_STRING

# Khóa Groq API
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b

# Khóa chức năng dev seed
E2E_SEED_ENABLED=false
GUSBY_API_BASE=
```

---

## 6. Chạy Migration Database

```bash
chmod +x ./scripts/migrate.sh
./scripts/migrate.sh
```

---

## 7. Biên Dịch Ứng Dụng Trên ARM64

### 7.1. Biên dịch Go Backend

Go hỗ trợ biên dịch trực tiếp trên ARM64 với hiệu năng cao:

```bash
CGO_ENABLED=0 go build -ldflags="-s -w" -o ./bin/gusby ./cmd/gusby
```

Kiểm tra:

```bash
./bin/gusby admin list
```

### 7.2. Biên dịch Frontend Nuxt (Static SPA)

Vì thiết bị di động có dung lượng RAM giới hạn, việc sinh file tĩnh SPA (`generate`) giúp loại bỏ hoàn toàn tiến trình Node.js khi chạy production, tiết kiệm 200MB - 400MB RAM:

```bash
cd frontend
npm ci
npm run generate
cd ..
```

---

## 8. Cấu Hình Nginx Trên Termux

Sao chép cấu hình Nginx của Gusby vào Termux:

```bash
mkdir -p "$PREFIX/etc/nginx/conf.d"
cp deploy/nginx/gusby-termux.conf "$PREFIX/etc/nginx/conf.d/gusby.conf"
```

Đảm bảo file `$PREFIX/etc/nginx/nginx.conf` có dòng include các file trong `conf.d`:

```nginx
http {
    ...
    include /data/data/com.termux/files/usr/etc/nginx/conf.d/*.conf;
}
```

Kiểm tra cú pháp và khởi động Nginx:

```bash
nginx -t
nginx
```

Nếu Nginx đã chạy trước đó, nạp lại cấu hình:

```bash
nginx -s reload
```

---

## 9. Quản Lý Tiến Trình Bằng PM2

Khởi động Go backend trong nền bằng PM2:

```bash
mkdir -p logs
pm2 start ecosystem.config.cjs
pm2 save
```

Kiểm tra trạng thái tiến trình:

```bash
pm2 status
pm2 logs gusby-backend
```

---

## 10. Vấn Đề Chạy Ngầm Của Android & Giải Pháp (Android Constraints)

Android có các cơ chế tiết kiệm năng lượng rất nghiêm ngặt (Doze Mode, App Standby, Battery Optimization) sẽ tự động tiêu diệt hoặc đóng băng các tiến trình nền của Termux khi màn hình tắt.

### 10.1. Kích hoạt Wake Lock (Bắt buộc)
Chạy lệnh sau trong Termux để giữ CPU không ngủ:

```bash
termux-wake-lock
```

Biểu tượng thông báo Termux sẽ hiển thị trạng thái `Wake lock held`.

### 10.2. Tắt Tối Ưu Hóa Pin (Disable Battery Optimization)
1. Vào mục **Cài đặt Android** (Settings) -> **Ứng dụng** (Apps) -> **Termux**.
2. Chọn **Pin** (Battery) -> Chọn **Không hạn chế** (Unrestricted).

### 10.3. Tự Động Khởi Động Khi Thiết Bị Khởi Động Lại (Termux:Boot)
Nếu cài ứng dụng **Termux:Boot**, tạo script tự chạy:

```bash
mkdir -p ~/.termux/boot
cat << 'EOF' > ~/.termux/boot/start-gusby.sh
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock

# Khởi động PostgreSQL
pg_ctl -D /data/data/com.termux/files/usr/var/lib/postgresql start

# Khởi động Nginx
nginx

# Khởi động lại các tiến trình PM2 đã lưu
pm2 resurrect
EOF

chmod +x ~/.termux/boot/start-gusby.sh
```

---

## 11. Tích Hợp Cloudflare Tunnel Đưa Ứng Dụng Ra Ngoài Internet

Vì thiết bị Android nằm sau mạng di động hoặc Wi-Fi (NAT/CGNAT không có IP công cộng và không mở port được), cách duy nhất an toàn để truy cập từ ngoài internet là sử dụng **Cloudflare Tunnel**.

### Cài đặt `cloudflared` trên Termux:

```bash
pkg install -y cloudflared
```

### Đăng nhập & Tạo Tunnel:

```bash
cloudflared tunnel login
cloudflared tunnel create gusby-lab
```

### Cấu hình file `~/.cloudflared/config.yml`:

```yaml
tunnel: YOUR_TUNNEL_ID
credentials-file: /data/data/com.termux/files/home/.cloudflared/YOUR_TUNNEL_ID.json

ingress:
  - hostname: gusby.yourdomain.com
    service: http://127.0.0.1:8080
  - service: http_status:404
```

### Chạy Cloudflare Tunnel trong nền bằng PM2:

```bash
pm2 start cloudflared --name "cf-tunnel" -- tunnel run
pm2 save
```

Giờ đây ứng dụng Gusby có thể truy cập toàn cầu qua `https://gusby.yourdomain.com` mà không cần mở port router, không lộ IP thiết bị và không cần quyền root.
