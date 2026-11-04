// ==============================================================================
// Gusby PM2 Ecosystem Process Manager Configuration
// ==============================================================================
// Usage:
//   pm2 start ecosystem.config.cjs
//   pm2 status
//   pm2 logs gusby-backend
//   pm2 restart all
//   pm2 stop all
//   pm2 save
//   pm2 resurrect
//
// Notes:
// - PostgreSQL is managed natively via pg_ctl (Termux) or systemd (Linux).
// - Nginx is managed natively via nginx / systemd.
// - Nuxt Frontend is deployed as static SPA files served directly by Nginx,
//   requiring zero PM2 process or Node.js runtime memory in production.
// - An optional SSR entry is provided below if Node-based SSR is ever required.

module.exports = {
  apps: [
    // --------------------------------------------------------------------------
    // 1. Primary Go Backend API & Background Queue Worker
    // --------------------------------------------------------------------------
    {
      name: 'gusby-backend',
      script: './bin/gusby',
      cwd: __dirname,
      exec_mode: 'fork',
      instances: 1, // Single instance to prevent redundant database connection spikes
      autorestart: true,
      restart_delay: 3000,
      max_restarts: 10,
      max_memory_restart: '256M', // Realistic memory limit for compiled Go binary
      kill_timeout: 10000, // 10s graceful shutdown window for in-flight jobs
      listen_timeout: 8000,
      env: {
        GUSBY_ENV: 'production',
        GUSBY_HOST: '127.0.0.1',
        GUSBY_PORT: '8081',
      },
      out_file: './logs/backend-out.log',
      error_file: './logs/backend-err.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
    },

    // --------------------------------------------------------------------------
    // 2. [OPTIONAL] Nuxt SSR Node Server
    // --------------------------------------------------------------------------
    // Disabled by default because Gusby uses Static SPA Generation (ssr: false).
    // If you explicitly build with `npm run build` instead of `npm run generate`,
    // you can enable this app block:
    /*
    {
      name: 'gusby-frontend-ssr',
      script: './frontend/.output/server/index.mjs',
      cwd: __dirname,
      exec_mode: 'fork',
      instances: 1,
      autorestart: true,
      restart_delay: 3000,
      max_memory_restart: '384M',
      env: {
        PORT: 3000,
        HOST: '127.0.0.1',
        NODE_ENV: 'production',
      },
      out_file: './logs/frontend-out.log',
      error_file: './logs/frontend-err.log',
    }
    */
  ],
};
