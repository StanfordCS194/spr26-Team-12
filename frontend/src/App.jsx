import { BrowserRouter, Routes, Route } from "react-router-dom";
import UploadPage from "./UploadPage";
import ResultsPage from "./ResultsPage";
import SharedReportPage from "./SharedReportPage";
import "./App.css";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/results/:analysisId" element={<ResultsPage />} />
        <Route path="/shared/:reportId" element={<SharedReportPage />} />
      </Routes>
    </BrowserRouter>
  );
}
