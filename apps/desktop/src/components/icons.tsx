import type { ReactNode, SVGProps } from "react";

/** Small stroke icon set (24px grid). Decorative by default — always pair with a visible label or aria-label on the control. */
const base = (children: ReactNode) => ({ size = 18, ...p }: { size?: number } & SVGProps<SVGSVGElement>) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false" {...p}>{children}</svg>
);

export const IconHome = base(<><path d="M3.5 11.2 12 4l8.5 7.2" /><path d="M5.5 10v9.5h13V10" /><path d="M10 19.5v-5h4v5" /></>);
export const IconTasks = base(<><rect x="4" y="4.5" width="16" height="15" rx="3" /><path d="m8.3 12.2 2.4 2.4 4.9-5" /></>);
export const IconMemory = base(<><ellipse cx="12" cy="6.5" rx="7" ry="2.8" /><path d="M5 6.5v5.2c0 1.6 3.1 2.8 7 2.8s7-1.2 7-2.8V6.5" /><path d="M5 11.7v5.3c0 1.6 3.1 2.8 7 2.8s7-1.2 7-2.8v-5.3" /></>);
export const IconTools = base(<><path d="M14.6 6.1a4 4 0 0 0-5.2 5.2l-5 5a1.8 1.8 0 0 0 2.5 2.5l5-5a4 4 0 0 0 5.2-5.2l-2.5 2.5-2.3-.5-.5-2.3 2.8-2.2Z" /></>);
export const IconFolder = base(<><path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7.5Z" /></>);
export const IconShield = base(<><path d="M12 3.5 5 6.2v5.4c0 4 2.8 7 7 8.9 4.2-1.9 7-4.9 7-8.9V6.2l-7-2.7Z" /><path d="m9.3 12 2 2 3.6-3.9" /></>);
export const IconActivity = base(<><path d="M3.5 12h4l2.4-6 4.2 12 2.4-6h4" /></>);
export const IconSettings = base(<><circle cx="12" cy="12" r="3" /><path d="M12 3.5v2.2M12 18.3v2.2M20.5 12h-2.2M5.7 12H3.5M18 6l-1.6 1.6M7.6 16.4 6 18M18 18l-1.6-1.6M7.6 7.6 6 6" /></>);
export const IconChat = base(<><path d="M4.5 6.5a2.5 2.5 0 0 1 2.5-2.5h10a2.5 2.5 0 0 1 2.5 2.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 3.5V16H7a2.5 2.5 0 0 1-2.5-2.5v-7Z" /></>);
export const IconMenu = base(<><path d="M4 7h16M4 12h16M4 17h16" /></>);
export const IconClose = base(<><path d="m6 6 12 12M18 6 6 18" /></>);
export const IconPlus = base(<><path d="M12 5v14M5 12h14" /></>);
export const IconSend = base(<><path d="M4.5 12 19.5 4.5 15 19.5l-3-6.3-7.5-1.2Z" /><path d="m12 13.2 7.5-8.7" /></>);
export const IconMic = base(<><rect x="9" y="3.5" width="6" height="11" rx="3" /><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5" /></>);
export const IconStop = base(<><rect x="6.5" y="6.5" width="11" height="11" rx="2.2" /></>);
export const IconHistory = base(<><path d="M4 12a8 8 0 1 0 2.5-5.8L4 8.5" /><path d="M4 4v4.5h4.5M12 8v4.5l3 1.8" /></>);
export const IconTrash = base(<><path d="M5 7h14M10 7V4.8h4V7M7 7l.8 12h8.4L17 7M10.3 11v5M13.7 11v5" /></>);
export const IconRefresh = base(<><path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4" /></>);
export const IconPanel = base(<><rect x="3.5" y="4.5" width="17" height="15" rx="3" /><path d="M15 4.5v15" /></>);
export const IconSidebar = base(<><rect x="3.5" y="4.5" width="17" height="15" rx="3" /><path d="M9 4.5v15" /></>);
export const IconLogs = base(<><path d="M6.5 3.5h8l4 4v13h-12v-17Z" /><path d="M14.5 3.5v4h4M9 12h6M9 15.5h6" /></>);
export const IconChevron = base(<><path d="m9 6 6 6-6 6" /></>);
export const IconBolt = base(<><path d="M13 3.5 5.5 13.5H11L10 20.5l7.5-10H12l1-7Z" /></>);
export const IconSkip = base(<><path d="M5 6.5v11l8-5.5-8-5.5ZM17 6v12" /></>);
