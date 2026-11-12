import { createRoot } from "react-dom/client";
import "./app.css";
import { DisplayApp } from "./display/DisplayApp";
import { HostApp } from "./host/HostApp";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");

const isHost = window.location.pathname.startsWith("/host");

createRoot(root).render(isHost ? <HostApp /> : <DisplayApp />);
