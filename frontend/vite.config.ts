import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// 開發時 /api 轉給後端（python -m codegraph_fable.web，預設 :8000）
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
});
