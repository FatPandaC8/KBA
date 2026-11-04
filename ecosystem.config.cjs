// ==============================================================================
// Gusby PM2 Ecosystem Process Manager Configuration
// ==============================================================================
// Target Host: Sony Xperia 1 (Android Termux ARM64)
//
// Usage:
//   pm2 start ecosystem.config.cjs
//   pm2 status
//   pm2 logs gusby-backend
//   pm2 restart gusby-backend
//   pm2 stop gusby-backend
//   pm2 save
//
// Notes:
// - PostgreSQL runs as an independent native service (managed via pg_ctl).
// - Nginx runs as an independent native reverse proxy on port 8080.
// - Frontend is a pre-rendered static Nuxt 4 SPA served directly by Nginx (0 MB PM2 memory).
// - Go Backend is managed here as a single fork instance with stable log paths.

const path = require('path');
const homeDir = process.env.HOME || '/data/data/com.termux/files/home';

// Production paths
const currentDir = process.env.GUSBY_CURRENT_DIR || path.join(homeDir, 'services/gusby/current');
const sharedDir = process.env.GUSBY_SHARED_DIR || path.join(homeDir, 'services/gusby/shared');
const logDir = path.join(sharedDir, 'logs');
const sharedEnvFile = path.join(sharedDir, '.env');

module.exports = {
  apps: [
    // --------------------------------------------------------------------------
    // 1. Primary Go Backend API & Background Job Worker
    // --------------------------------------------------------------------------
    {
      name: 'gusby-backend',
      script: './bin/gusby',
      cwd: currentDir,
      exec_mode: 'fork',
      instances: 1, // Single instance to prevent redundant database connection spikes
      autorestart: true,
      restart_delay: 3000,
      max_restarts: 10,
      max_memory_restart: '256M', // Bounded memory limit for mobile ARM64 host
      kill_timeout: 10000,        // 10s graceful shutdown window for in-flight jobs
      listen_timeout: 8000,
      env: {
        GUSBY_ENV: 'production',
        GUSBY_HOST: '127.0.0.1',
        GUSBY_PORT: '8081',
        GUSBY_ENV_FILE: sharedEnvFile,
      },
      out_file: path.join(logDir, 'backend-out.log'),
      error_file: path.join(logDir, 'backend-err.log'),
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
    },
  ],
};
