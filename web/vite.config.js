import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'
import pwa from 'vite-plugin-pwa'
import path from 'path'

console.log('当前环境:', process.env.NODE_ENV)
// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    pwa({
      registerType: 'autoUpdate',
      manifest: {
        name: '御阪网络弹幕服务',
        short_name: '御阪弹幕',
        description:
          '一个功能强大的自托管弹幕（Danmaku）聚合与管理服务，兼容 dandanplay API 规范。',
        icons: [{
            src: 'images/pwa-48x48.png',
            sizes: '48x48',
            type: 'image/png',
          },{
            src: 'images/pwa-96x96.png',
            sizes: '96x96',
            type: 'image/png',
          },
          {
            src: 'images/pwa-192x192.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: 'images/pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png',
          },
        ],
        display: 'standalone',
        background_color: '#ffffff',
        theme_color: '#000000',
        start_url: '/',
        prefer_related_applications: true,
      },
    }),
  ],
  css: {
    preprocessorOptions: {
      less: {
        javascriptEnabled: true,
        modifyVars: {},
      },
    },
  },
  build: {
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: process.env.NODE_ENV !== 'development',
        drop_debugger: process.env.NODE_ENV !== 'development',
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
