import { useState, useEffect } from "react";

function App() {
  const [backendStatus, setBackendStatus] = useState<string>("checking...");

  useEffect(() => {
    fetch("/api/health")
      .then((res) => res.json())
      .then((data) => setBackendStatus(data.status ?? "unknown"))
      .catch(() => setBackendStatus("unreachable"));
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col items-center justify-center">
      <h1 className="text-4xl font-bold mb-4">Mini-OpenClaw</h1>
      <p className="text-gray-400 mb-2">
        Lightweight local-first AI agent with auditable tool execution
      </p>
      <p className="text-sm">
        Backend:{" "}
        <span
          className={
            backendStatus === "ok" ? "text-green-400" : "text-yellow-400"
          }
        >
          {backendStatus}
        </span>
      </p>
    </div>
  );
}

export default App;
