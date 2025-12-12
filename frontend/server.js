import express from "express";
import compression from "compression";
import cors from "cors";
import morgan from "morgan";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const port = process.env.PORT || 5173;
const wsUrl = process.env.WS_URL || "ws://localhost:8000/ws/interview";
const apiUrl = process.env.API_URL || "http://localhost:8000";

app.use(cors());
app.use(compression());
app.use(morgan("dev"));

// Serve a tiny config script so the client can pick up the WS URL
app.get("/config.js", (_req, res) => {
  res
    .type("application/javascript")
    .send(`window.__APP_CONFIG__ = { WS_URL: "${wsUrl}", API_URL: "${apiUrl}" };`);
});

app.use(express.static(__dirname));

app.listen(port, () => {
  console.log(`Frontend server running at http://localhost:${port}`);
  console.log(`Backend WS URL set to ${wsUrl}`);
});



