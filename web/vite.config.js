import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa' // 修正：使用命名导入
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // 修正：使用 VitePWA() 而不是 pwa()
    VitePWA({
      registerType: 'autoUpdate',
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg}'],
      },
      manifest: {
        name: '御坂网络弹幕服务',
        short_name: '御坂弹幕',
        description: '一个功能强大的自托管弹幕（Danmaku）聚合与管理服务',
        theme_color: '#ffffff',
        icons: [
          {
            src: 'images/logo-192.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: 'images/logo-512.png',
            sizes: '512x512',
            type: 'image/png',
          },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // 开发时代理后端API，避免跨域问题
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:7768',
        changeOrigin: true,
      },
    },
  },
})

