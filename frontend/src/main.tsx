import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { CardViewerProvider } from "./components/CardViewer";
import { Home } from "./pages/Home";
import { NewExpedition } from "./pages/NewExpedition";
import { Play } from "./pages/Play";
import { Preview } from "./pages/Preview";
import "./styles.css";

function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <CardViewerProvider>
      <div className="topbar">
        <Link to="/" className="brand">
          <img src="/favicon.svg" alt="" width={24} height={24} /> Aeon's Expeditions
        </Link>
      </div>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/new" element={<NewExpedition />} />
        <Route path="/preview" element={<Preview />} />
        <Route path="/play/:id" element={<Play />} />
        <Route path="*" element={<Home />} />
      </Routes>
      </CardViewerProvider>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
