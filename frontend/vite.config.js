import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { lingui } from '@lingui/vite-plugin';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8090';
// https://vite.dev/config/
export default defineConfig({
    // Lingui compiles .po catalogs on import and expands its macros natively,
    // so no Babel pass is added to the build.
    plugins: [react(), lingui({ macroTransform: true })],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "./src"),
        },
    },
    server: {
        proxy: {
            '/api': {
                target: apiProxyTarget,
                changeOrigin: true,
            },
            '/auth': {
                target: apiProxyTarget,
                changeOrigin: true,
            },
        },
    },
});
