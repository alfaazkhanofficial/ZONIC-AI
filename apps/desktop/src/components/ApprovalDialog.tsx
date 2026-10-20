import { useStore } from "../lib/store";
import { Btn, Chip, Modal } from "./ui";

/** Global approval prompt: nothing risky happens until a person presses Approve here. Focus starts on Deny. */
export function ApprovalDialog() {
  const approvals = useStore((s) => s.approvals);
  const tasks = useStore((s) => s.tasks);
  const decide = useStore((s) => s.decide);
  const a = approvals[0];
  if (!a) return null;
  const task = tasks.find((t) => t.id === a.task_id);
  const isSkill = a.kind === "register_skill";
  return (
    <Modal title={isSkill ? "Approve a new skill?" : "Approve this action?"} amber role="alertdialog" initialFocus="button.deny">
      <div className="col">
        <div className="row"><Chip state={a.risk_level} label={`${a.risk_level[0].toUpperCase() + a.risk_level.slice(1)} risk`} />{approvals.length > 1 && <span className="muted small">{approvals.length - 1} more waiting</span>}</div>
        <p style={{ fontSize: 15, margin: 0 }}>{a.action_summary}</p>
        {task && <p className="muted small" style={{ margin: 0 }}>Requested while working on: “{task.goal}”</p>}
        <p className="muted small" style={{ margin: 0 }}>{isSkill ? "Approving makes this skill available to run. It contains no code and each step is still permission-checked." : "Nothing happens until you approve. Denying changes nothing."}</p>
        <div className="row spread">
          <Btn className="deny" onClick={() => void decide(a.id, false)}>Deny</Btn>
          <Btn kind="primary" onClick={() => void decide(a.id, true)}>Approve</Btn>
        </div>
      </div>
    </Modal>
  );
}
