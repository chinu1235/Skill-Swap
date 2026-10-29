import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteStaticCopy } from 'vite-plugin-static-copy';

export default defineConfig({
  server: {
    host: 'localhost',
    port: 5174,
    strictPort: true
  },
  plugins: [
    react(),
    viteStaticCopy({
      targets: [{ src: 'node_modules/monaco-editor/min/vs', dest: 'monaco-editor/min' }]
    })
  ]
});
