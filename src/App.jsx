import { Routes, Route } from "react-router-dom";
import JobsPage from "./JobsPage";
import ApplyWithAI from "./ApplyWithAI";
import "./App.css";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<JobsPage />} />
      <Route path="/apply-with-ai" element={<ApplyWithAI />} />
    </Routes>
  );
}
