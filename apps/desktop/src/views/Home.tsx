import { ActiveTaskCard, CapabilitiesCard, QuickActionsCard, RecentActivityCard, RecentConversationsCard, SystemStatusCard } from "../components/Cards";
import { AICore } from "../components/AICore";
import { useStore } from "../lib/store";
import { Note } from "../components/ui";

/** HomeDashboard: AI Core hero + card grid. The grid reflows with the centre column's width (auto-fit), never the window's. */
export function HomeDashboard() {
  const status = useStore((s) => s.status);
  const setView = useStore((s) => s.setView);
  return (
    <div className="dash">
      {status?.limited_mode && <div className="span-all"><Note warn>Limited mode: no model is connected yet, so ZONIC can’t reason or act. <a href="#" onClick={(e) => { e.preventDefault(); setView("settings"); }}>Add your NVIDIA API key</a></Note></div>}
      <AICore />
      <SystemStatusCard />
      <ActiveTaskCard />
      <QuickActionsCard />
      <RecentActivityCard />
      <RecentConversationsCard />
      <CapabilitiesCard />
    </div>
  );
}
