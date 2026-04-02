import type { Express } from "express";
import type { Server } from "http";

// RT Viewer uses a separate FastAPI backend on port 8000.
// This Express server only serves the static frontend assets.
export function registerRoutes(httpServer: Server, app: Express): void {
  app.get("/api/health", (_req, res) => {
    res.json({ status: "ok", service: "rt-viewer-frontend" });
  });
}
