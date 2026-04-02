import { useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/lib/queryClient";
import PatientList from "@/pages/PatientList";
import Viewer from "@/pages/Viewer";

export default function App() {
  const [selectedCase, setSelectedCase] = useState<string | null>(null);

  return (
    <QueryClientProvider client={queryClient}>
      <div className="dark">
        {selectedCase ? (
          <Viewer
            caseId={selectedCase}
            onBack={() => setSelectedCase(null)}
          />
        ) : (
          <PatientList onSelectCase={setSelectedCase} />
        )}
      </div>
    </QueryClientProvider>
  );
}
