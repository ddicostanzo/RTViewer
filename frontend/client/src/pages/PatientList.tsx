import { useState, useMemo, useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE } from "@/lib/queryClient";
import type { PatientRecord, PatientCaseEntry } from "@/types";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Search, RefreshCw, ChevronRight, Activity, Radio } from "lucide-react";

interface PatientListProps {
  onSelectCase: (caseId: string) => void;
}

function formatDate(iso: string) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short", day: "numeric", year: "numeric",
    });
  } catch { return iso; }
}

function CaseRow({ entry, onSelect }: { entry: PatientCaseEntry; onSelect: () => void }) {
  return (
    <button
      className="w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-md hover:bg-secondary/70 transition-colors group"
      onClick={onSelect}
      data-testid={`case-row-${entry.case_id.replace(/\//g, "-")}`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground truncate">{entry.plan_name}</span>
          {entry.beamset_labels.length > 0 && (
            <div className="flex gap-1 flex-wrap">
              {entry.beamset_labels.map(bs => (
                <Badge key={bs} variant="outline" className="text-xs py-0 border-primary/30 text-primary/80">
                  {bs}
                </Badge>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 mt-0.5">
          <span className="text-xs text-muted-foreground">{entry.case_name}</span>
          {entry.exam_name && (
            <span className="text-xs text-muted-foreground/60">· {entry.exam_name}</span>
          )}
          {entry.dose_type && (
            <Badge variant="secondary" className="text-xs py-0 h-4">
              {entry.dose_type}
            </Badge>
          )}
          {entry.exported_at && (
            <span className="text-xs text-muted-foreground/50 ml-auto">
              {formatDate(entry.exported_at)}
            </span>
          )}
        </div>
      </div>
      <ChevronRight className="w-4 h-4 text-muted-foreground/40 group-hover:text-primary transition-colors flex-shrink-0" />
    </button>
  );
}

function PatientCard({
  record,
  query,
  onSelectCase,
}: {
  record: PatientRecord;
  query: string;
  onSelectCase: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasDose = record.cases.some(c => c.beamset_labels.length > 0);

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      {/* Patient header */}
      <button
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-secondary/40 transition-colors text-left"
        onClick={() => setExpanded(e => !e)}
        data-testid={`patient-header-${record.patient_id}`}
      >
        <div className="w-8 h-8 rounded-full bg-primary/15 flex items-center justify-center flex-shrink-0">
          <Activity className="w-4 h-4 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold mono text-foreground">{record.patient_id}</span>
            {record.patient_name && record.patient_name !== "Unknown" && (
              <span className="text-sm text-muted-foreground truncate">{record.patient_name}</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {record.cases.length} plan{record.cases.length !== 1 ? "s" : ""}
            {hasDose ? " · dose" : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="text-xs">{record.cases.length}</Badge>
          <ChevronRight
            className={`w-4 h-4 text-muted-foreground/50 transition-transform ${expanded ? "rotate-90" : ""}`}
          />
        </div>
      </button>

      {/* Case list */}
      {expanded && (
        <div className="border-t border-border px-2 py-1.5 space-y-0.5">
          {record.cases.map(entry => (
            <CaseRow
              key={entry.case_id}
              entry={entry}
              onSelect={() => onSelectCase(entry.case_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function PatientList({ onSelectCase }: PatientListProps) {
  const [query, setQuery] = useState("");
  const [watcherConnected, setWatcherConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const esRef = useRef<EventSource | null>(null);

  const { data: patients, isLoading, isError } = useQuery<PatientRecord[]>({
    queryKey: ["/api/patients"],
    queryFn: () => fetch(`${API_BASE}/api/patients`).then(r => r.json()),
  });

  // Subscribe to SSE stream — auto-refreshes patient list on watcher events
  useEffect(() => {
    const url = `${API_BASE}/api/events`;
    let es: EventSource;
    let retryTimer: ReturnType<typeof setTimeout>;

    function connect() {
      es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => setWatcherConnected(true);

      es.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.event === "patients_updated") {
            queryClient.invalidateQueries({ queryKey: ["/api/patients"] });
            setLastUpdate(new Date().toLocaleTimeString());
          }
        } catch {}
      };

      es.onerror = () => {
        setWatcherConnected(false);
        es.close();
        // Reconnect after 5 s
        retryTimer = setTimeout(connect, 5000);
      };
    }

    connect();
    return () => {
      clearTimeout(retryTimer);
      esRef.current?.close();
      setWatcherConnected(false);
    };
  }, []);

  const filtered = useMemo(() => {
    if (!patients) return [];
    const q = query.toLowerCase().trim();
    if (!q) return patients;
    return patients.filter(p =>
      p.patient_id.toLowerCase().includes(q) ||
      p.patient_name.toLowerCase().includes(q) ||
      p.cases.some(c =>
        c.plan_name.toLowerCase().includes(q) ||
        c.case_name.toLowerCase().includes(q) ||
        c.beamset_labels.some(bs => bs.toLowerCase().includes(q))
      )
    );
  }, [patients, query]);

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ["/api/patients"] });
  }

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-6 py-4 flex items-center gap-3">
        <svg viewBox="0 0 32 32" width="28" height="28" fill="none" aria-label="RT Viewer logo">
          <circle cx="16" cy="16" r="12" stroke="hsl(188 35% 47%)" strokeWidth="1.5"/>
          <circle cx="16" cy="16" r="4.5" fill="hsl(188 35% 47%)"/>
          <line x1="16" y1="4" x2="16" y2="10" stroke="hsl(188 35% 47%)" strokeWidth="2" strokeLinecap="round"/>
          <line x1="16" y1="22" x2="16" y2="28" stroke="hsl(188 35% 47%)" strokeWidth="2" strokeLinecap="round"/>
          <line x1="4" y1="16" x2="10" y2="16" stroke="hsl(188 35% 47%)" strokeWidth="2" strokeLinecap="round"/>
          <line x1="22" y1="16" x2="28" y2="16" stroke="hsl(188 35% 47%)" strokeWidth="2" strokeLinecap="round"/>
        </svg>
        <div>
          <h1 className="text-sm font-semibold text-foreground tracking-tight">RT Viewer</h1>
          <p className="text-xs text-muted-foreground">Radiation Therapy DICOM Viewer</p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {/* Live watcher status */}
          <div className="flex items-center gap-1.5" title={watcherConnected ? "Watching dicom_data for new exports" : "Reconnecting to watcher..."}>
            <div className={`w-1.5 h-1.5 rounded-full ${watcherConnected ? "bg-emerald-500 animate-pulse" : "bg-muted-foreground/40"}`} />
            <span className="text-xs text-muted-foreground">
              {watcherConnected ? "Live" : "Offline"}
            </span>
          </div>
          {lastUpdate && (
            <span className="text-xs text-muted-foreground/50">Updated {lastUpdate}</span>
          )}
          <button
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-2.5 py-1.5 rounded-md hover:bg-secondary"
            onClick={handleRefresh}
            title="Refresh now"
            data-testid="btn-refresh"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </header>

      <main className="flex-1 max-w-2xl mx-auto w-full px-6 py-6">
        {/* Search bar */}
        <div className="relative mb-5">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Filter by MRN, patient name, plan, or beamset…"
            className="pl-9 bg-card border-border mono text-sm"
            value={query}
            onChange={e => setQuery(e.target.value)}
            data-testid="input-search"
          />
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-24 w-full rounded-lg" />)}
          </div>
        )}

        {/* Error */}
        {isError && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
            <p className="font-medium">Cannot connect to API server</p>
            <p className="text-xs mt-1 text-destructive/70">
              Make sure <code className="font-mono">api_server.py</code> is running on port 8000.
            </p>
          </div>
        )}

        {/* Empty */}
        {!isLoading && !isError && filtered.length === 0 && (
          <div className="rounded-lg border border-border bg-card p-8 text-center">
            {query ? (
              <>
                <p className="text-sm text-muted-foreground">No results for "{query}"</p>
                <button className="text-xs text-primary mt-2 hover:underline" onClick={() => setQuery("")}>
                  Clear filter
                </button>
              </>
            ) : (
              <>
                <p className="text-sm text-muted-foreground">No patients exported yet.</p>
                <p className="text-xs text-muted-foreground/60 mt-2 max-w-sm mx-auto">
                  Run <code className="font-mono">raystation_export.py</code> inside RayStation to export
                  a patient's CT, structures, and dose to the <code className="font-mono">dicom_data/</code> folder,
                  then click Refresh.
                </p>
              </>
            )}
          </div>
        )}

        {/* Patient cards */}
        {filtered.length > 0 && (
          <div className="space-y-3">
            {filtered.map(record => (
              <PatientCard
                key={record.patient_id}
                record={record}
                query={query}
                onSelectCase={onSelectCase}
              />
            ))}
          </div>
        )}

        {/* Count summary */}
        {patients && patients.length > 0 && (
          <p className="text-xs text-muted-foreground/50 text-center mt-6">
            {filtered.length} of {patients.length} patient{patients.length !== 1 ? "s" : ""}
            {" · "}
            {patients.reduce((n, p) => n + p.cases.length, 0)} plans total
          </p>
        )}
      </main>

      <footer className="px-6 py-3 border-t border-border text-xs text-muted-foreground/50 text-center">
        RT Viewer · DICOM CT / RTStruct / RTDose · Research use only
      </footer>
    </div>
  );
}
