/**
 * HistoryPage — displays run history for the current session.
 */

import RunHistory from "../components/RunHistory";

interface HistoryPageProps {
  sessionId: string;
}

export default function HistoryPage({ sessionId }: HistoryPageProps) {
  return (
    <div className="h-full overflow-y-auto">
      <RunHistory sessionId={sessionId} />
    </div>
  );
}
