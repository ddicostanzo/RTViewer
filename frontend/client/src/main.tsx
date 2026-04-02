import App from "./App";
import { createRoot } from "react-dom/client";
import "./index.css";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("No root element");
createRoot(rootEl).render(<App />);
