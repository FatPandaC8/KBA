// ==============================================================================
// Gusby PM2 Configuration — Android Termux
// ==============================================================================
// Executes: ~/services/gusby/bin/gusby
// Logs:     ~/services/gusby/logs/
// Config:   ~/services/gusby/.env

const path = require('path');
const homeDir = process.env.HOME || '/data/data/com.termux/files/home';
const serviceDir = path.join(homeDir, 'services/gusby');

module.exports = {
  apps: [
    {
      name: 'gusby-backend',
      script: './bin/gusby',
      cwd: serviceDir,
      exec_mode: 'fork',
      instances: 1,
      autorestart: true,
      restart_delay: 3000,
      max_memory_restart: '256M',
      env: {
        GUSBY_ENV: 'production',
        GUSBY_HOST: '127.0.0.1',
        GUSBY_PORT: '8081',
        GUSBY_ENV_FILE: path.join(serviceDir, '.env'),
      },
      out_file: path.join(serviceDir, 'logs/backend-out.log'),
      error_file: path.join(serviceDir, 'logs/backend-err.log'),
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
    },
  ],
};
