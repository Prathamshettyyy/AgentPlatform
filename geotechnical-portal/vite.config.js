import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
export default defineConfig(function (_a) {
    var mode = _a.mode;
    var env = loadEnv(mode, process.cwd(), '');
    var backendUrl = env.VITE_API_BASE_URL || 'http://127.0.0.1:8001';
    return {
        plugins: [react()],
        optimizeDeps: {
            include: ['react', 'react-dom', 'lucide-react', 'clsx', 'tailwind-merge'],
        },
        resolve: {
            alias: {
                '@': path.resolve(__dirname, './src'),
            },
        },
        server: {
            port: 5174,
            proxy: {
                '/v1': {
                    target: backendUrl,
                    changeOrigin: true,
                },
            },
        },
        test: {
            globals: true,
            environment: 'jsdom',
            setupFiles: './src/test/setup.ts',
        },
    };
});
