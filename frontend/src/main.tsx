import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, Route, Routes, useLocation } from "react-router-dom";
import { CardViewerProvider } from "./components/CardViewer";
import { Home } from "./pages/Home";
import { NewExpedition } from "./pages/NewExpedition";
import { Play } from "./pages/Play";
import { Preview } from "./pages/Preview";
// Cinzel: engraved small capitals like the card titles; EB Garamond: the rules / flavor text (bundled, no font CDN)
import "@fontsource/cinzel/latin-600.css";
import "@fontsource/cinzel/latin-700.css";
import "@fontsource/eb-garamond/latin-400.css";
import "@fontsource/eb-garamond/latin-400-italic.css";
import "@fontsource/eb-garamond/latin-600.css";
import "./styles.css";

/** The cover-style painting behind the page: in full on the home page, dimmed behind the other pages. */
function Backdrop() {
  const home = useLocation().pathname === "/";
  return <div className={`backdrop${home ? " home" : ""}`} aria-hidden="true" />;
}

function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <CardViewerProvider>
      <Backdrop />
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
