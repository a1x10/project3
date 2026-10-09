// Запуск через PM2:  pm2 start ecosystem.config.cjs && pm2 save && pm2 startup
module.exports = {
  apps: [
    {
      name: 'homework-bot',
      script: 'src/index.js',
      cwd: __dirname,
      instances: 1, // только одна копия! две копии с одной сессией WhatsApp будут выбивать друг друга
      autorestart: true,
      max_memory_restart: '500M',
      exp_backoff_restart_delay: 2000,
      time: true,
      env: {
        NODE_ENV: 'production',
      },
    },
  ],
};
