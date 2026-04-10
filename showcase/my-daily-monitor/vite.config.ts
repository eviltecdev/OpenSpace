import { defineConfig } from 'vite';
import { resolve } from 'path';
import { apiPlugin } from './vite-api-plugin';

export default defineConfig({
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  plugins: [
    apiPlugin(),  // Embeds API routes directly — no separate server needed
  ],
  server: {
    host: '0.0.0.0',
    port: 5173,
  },
});
