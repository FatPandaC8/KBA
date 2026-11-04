# Hướng Dẫn Triển Khai Gusby Tối Giản Trên Android Termux

Tài liệu này được rút gọn tối đa, đồng bộ với [ANDROID_TERMUX.md](./ANDROID_TERMUX.md).

---

## 1. Kiến Trúc Tối Giản

- Kho mã nguồn Git: `~/apps/gusby`
- Thư mục runtime sản xuất duy nhất:
  ```text
  ~/services/gusby/
  ├── .env            # Cấu hình sản xuất (chmod 600)
  ├── bin/
  │   └── gusby       # File thực thi backend
  ├── frontend/       # File tĩnh Nuxt SPA
  └── logs/           # Log hệ thống
  ```

---

## 2. Các Lệnh Thao Tác Cơ Bản

### Khởi tạo lần đầu:
```bash
# 1. Khởi động PostgreSQL và tạo database gusby_db (bảo toàn server_lab)
pg_ctl -D "$PREFIX/var/lib/postgresql" -l "$PREFIX/var/log/postgresql.log" start
psql -d postgres -c "CREATE USER gusby_user WITH PASSWORD 'MAT_KHAU_MANH';"
psql -d postgres -c "CREATE DATABASE gusby_db OWNER gusby_user;"
psql -d gusby_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# 2. Tạo cấu hình môi trường
mkdir -p ~/services/gusby/bin ~/services/gusby/frontend ~/services/gusby/logs
cp ~/apps/gusby/.env.example ~/services/gusby/.env
chmod 600 ~/services/gusby/.env

# 3. Chạy migration ban đầu
cd ~/apps/gusby
./scripts/migrate.sh up

# 4. Cấu hình Nginx
cp deploy/nginx/gusby-termux.conf "$PREFIX/etc/nginx/conf.d/gusby.conf"
nginx -t && nginx
```

### Triển khai ứng dụng (Normal Deployment):
```bash
cd ~/apps/gusby
./deploy/termux/deploy.sh
```

### Kiểm tra sức khỏe:
```bash
./deploy/termux/verify.sh
```

### Chạy migration thủ công khi có cập nhật schema:
```bash
./scripts/migrate.sh up
```
