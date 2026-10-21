import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
    // Load .env, .env.development, .env.production, etc.
    const env = loadEnv(mode, process.cwd(), "");

    const host =
        env.VITE_HOST === "true" || env.VITE_HOST === true
            ? true
            : env.VITE_HOST || "localhost";

    return {
        base: env.VITE_BASE_URL || "/",

        plugins: [react()],

        server: {
            port: Number(env.VITE_PORT || 3005),
            host,

            allowedHosts: env.VITE_ALLOWED_HOSTS
                ? env.VITE_ALLOWED_HOSTS.split(",").map((host) => host.trim())
                : [],

            proxy: {
                "/api": {
                    target: env.VITE_API_URL || "http://localhost:2528",

                    changeOrigin: true,
                    secure: false,

                    configure: (proxy) => {
                        proxy.on("error", (err) => {
                            console.log("[proxy] error", err.message);
                        });
                    },
                },
            },
        },

        preview: {
            port: Number(env.VITE_PREVIEW_PORT || env.VITE_PORT || 3005),
            host,

            allowedHosts: env.VITE_ALLOWED_HOSTS
                ? env.VITE_ALLOWED_HOSTS.split(",").map((host) => host.trim())
                : [],
        },

        build: {
            rollupOptions: {
                output: {
                    manualChunks: (id) => {
                        if (
                            id.includes("node_modules/react/") ||
                            id.includes("node_modules/react-dom/") ||
                            id.includes("node_modules/react-router") ||
                            id.includes("node_modules/scheduler/")
                        ) {
                            return "vendor-react";
                        }

                        if (id.includes("node_modules/@mui/material/")) {
                            return "vendor-mui-core";
                        }

                        if (id.includes("node_modules/@mui/icons-material/")) {
                            return "vendor-mui-icons";
                        }

                        if (
                            id.includes("node_modules/@mui/system/") ||
                            id.includes("node_modules/@mui/styled-engine") ||
                            id.includes("node_modules/@mui/utils/")
                        ) {
                            return "vendor-mui-system";
                        }

                        if (id.includes("node_modules/@emotion/")) {
                            return "vendor-emotion";
                        }

                        if (id.includes("node_modules/")) {
                            if (
                                !id.includes("@mui/") &&
                                !id.includes("react")
                            ) {
                                return "vendor-others";
                            }
                        }
                    },
                },
            },

            chunkSizeWarningLimit: 600,
        },
    };
});
