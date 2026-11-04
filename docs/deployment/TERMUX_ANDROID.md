# Hướng Dẫn Triển Khai Gusby Trên Android Termux ARM64 (VPS Lab)

> [!NOTE]
> Tài liệu này được đồng bộ với tài liệu sản xuất chính thức: [ANDROID_TERMUX.md](./ANDROID_TERMUX.md).  
> Toàn bộ quy trình dưới đây tuân thủ kiến trúc triển khai độc lập, bảo toàn cơ sở dữ liệu `server_lab`, và phân tách rõ ràng giữa mã nguồn (`~/apps/gusby`) và thư mục thực thi runtime (`~/services/gusby`).

---

## 1. Nguyên Tắc Cốt Lõi

1. **Vòng đời cơ sở dữ liệu độc lập hoàn toàn**:
   - PostgreSQL được quản lý riêng qua `pg_ctl`.
   - Quá trình deploy ứng dụng thông thường **tuyệt đối không**: restart PostgreSQL, chạy migration, tạo/xóa bảng, hoặc backup/restore tự động.
2. **Cơ sở dữ liệu dành riêng cho Gusby**:
   - Sử dụng database riêng biệt: `gusby_db` với user `gusby_user`.
   - Cơ sở dữ liệu `server_lab` được bảo toàn nguyên vẹn, không bao giờ truy cập hay sửa đổi.
3. **Phân tách thư mục rõ ràng**:
   - Kho mã nguồn Git: `~/apps/gusby`
   - Thư mục runtime sản xuất: `~/services/gusby`
4. **Kiểm duyệt CI trước khi deploy**:
   - Chỉ các commit đã vượt qua thành công quy trình GitHub Actions CI (`Gusby Production CI`) mới được phép triển khai.

---

## 2. Thiết Lập Lần Đầu (First-Time Setup)

### Bước 1: Khởi động PostgreSQL & Tạo Database `gusby_db`
```bash
# Khởi động PostgreSQL
pg_ctl -D "$PREFIX/var/lib/postgresql" -l "$PREFIX/var/log/postgresql.log" start

# Tạo tài khoản và database riêng biệt (KHÔNG đụng vào server_lab)
psql -d postgres -c "CREATE USER gusby_user WITH PASSWORD 'YOUR_STRONG_PASSWORD';"
psql -d postgres -c "CREATE DATABASE gusby_db OWNER gusby_user;"
psql -d gusby_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### Bước 2: Thiết lập thư mục runtime sản xuất & Biến môi trường
```bash
mkdir -p ~/services/gusby/shared/logs ~/services/gusby/backups ~/services/gusby/state
cd ~/apps/gusby
cp .env.example ~/services/gusby/shared/.env
chmod 600 ~/services/gusby/shared/.env
```

Cấu hình file `~/services/gusby/shared/.env` với thông tin sản xuất:
```ini
GUSBY_ENV=production
GUSBY_HOST=127.0.0.1
GUSBY_PORT=8081
GUSBY_DATABASE_URL=postgresql://gusby_user:YOUR_STRONG_PASSWORD@127.0.0.1:5432/gusby_db?sslmode=disable
GUSBY_EXPECTED_DB=gusby_db
GUSBY_SESSION_SECRET=YOUR_32_CHAR_SECRET_FROM_OPENSSL
GROQ_API_KEY=your_groq_api_key
```

### Bước 3: Chạy Migration khởi tạo lần đầu
```bash
cd ~/apps/gusby
./scripts/migrate.sh validate
./scripts/migrate.sh up
./scripts/migrate.sh status
```

### Bước 4: Cấu hình Nginx
```bash
mkdir -p "$PREFIX/etc/nginx/conf.d"
cp deploy/nginx/gusby-termux.conf "$PREFIX/etc/nginx/conf.d/gusby.conf"
nginx -t
nginx
```

---

## 3. Triển Khai Ứng Dụng Hàng Ngày (Normal Deployment)

Khi có bản cập nhật mã nguồn đã pass CI:

```bash
cd ~/apps/gusby

# Triển khai commit mới nhất pass CI trên branch main:
./deploy/termux/deploy.sh

# Hoặc triển khai một commit SHA cụ thể:
./deploy/termux/deploy.sh <commit_sha>
```

Script sẽ tự động:
1. Xác minh commit đã pass GitHub Actions CI (`Gusby Production CI`).
2. Build Go binary cho ARM64 và generate Nuxt 4 static SPA.
3. Chuyển đổi symlink `~/services/gusby/current` sang release mới.
4. Restart backend thông qua PM2 (`pm2 restart gusby-backend`).
5. Chạy bộ kiểm tra sức khỏe `deploy/termux/verify.sh`.
6. Tự động rollback về release trước đó nếu kiểm tra thất bại.

---

## 4. Chạy Migration Cơ Sở Dữ Liệu Thủ Công

Migration **chỉ chạy khi có thay đổi schema** và được thực hiện riêng biệt ngoài quy trình deploy:

```bash
cd ~/apps/gusby
./scripts/migrate.sh status     # Xem danh sách pending (Read-only)
./scripts/migrate.sh up         # Thực thi migration (Tự động backup an toàn trước khi chạy)
```

---

## 5. Kiểm Tra Trạng Thái & Khôi Phục (Recovery)

```bash
# Kiểm tra tình trạng sức khỏe ứng dụng (Read-only):
./deploy/termux/verify.sh

# Xem trạng thái tổng quát của hệ thống:
./deploy/termux/status.sh

# Khôi phục về phiên bản trước (Rollback tức thời):
./deploy/termux/rollback.sh
```
