import { Check } from "lucide-react";
import { type Step, type RunDetail } from "./api";
import { Status } from "./components";

export default function PipelineGraph({
  steps,
  selected,
  run,
  onSelect,
}: {
  steps: Step[];
  selected: string;
  run?: RunDetail;
  onSelect: (name: string) => void;
}) {
  const byName = new Map(steps.map((step) => [step.name, step]));
  const levels = new Map<string, number>();
  function depth(name: string): number {
    if (levels.has(name)) return levels.get(name)!;
    const parents = byName
      .get(name)!
      .depends_on.filter((parent) => byName.has(parent));
    const level = parents.length ? Math.max(...parents.map(depth)) + 1 : 0;
    levels.set(name, level);
    return level;
  }
  steps.forEach((step) => depth(step.name));
  const ranks = Array.from(
    { length: Math.max(...levels.values()) + 1 },
    (_, level) => steps.filter((step) => levels.get(step.name) === level),
  );
  const positions = new Map(
    ranks.flatMap((rank, level) =>
      rank.map(
        (step, index) =>
          [
            step.name,
            {
              x: ((index + 0.5) * 1000) / rank.length,
              y: level * 142 + 12,
              width: Math.min(800, 900 / rank.length),
            },
          ] as const,
      ),
    ),
  );
  const height = ranks.length * 142;
  return (
    <div className="graph-scroll">
      <div
        className="pipeline-graph"
        style={{ height }}
        role="group"
        aria-label="Pipeline dependency graph"
      >
        <svg
          viewBox={`0 0 1000 ${height}`}
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {steps.flatMap((step) =>
            step.depends_on
              .filter((parent) => byName.has(parent))
              .map((parent) => {
                const from = positions.get(parent)!,
                  to = positions.get(step.name)!;
                return (
                  <path
                    key={`${parent}-${step.name}`}
                    d={`M ${from.x} ${from.y + 105} C ${from.x} ${from.y + 125}, ${to.x} ${to.y - 22}, ${to.x} ${to.y}`}
                    className={
                      selected === parent || selected === step.name
                        ? "active-edge"
                        : ""
                    }
                  />
                );
              }),
          )}
        </svg>
        {steps.map((step) => {
          const position = positions.get(step.name)!;
          const execution = run?.steps.find((item) => item.name === step.name);
          return (
            <button
              key={step.name}
              className={
                "graph-node " + (selected === step.name ? "selected" : "")
              }
              style={{
                left: `${position.x / 10}%`,
                top: position.y,
                width: `${position.width / 10}%`,
              }}
              onClick={() => onSelect(step.name)}
            >
              <div className="graph-node-head">
                <code>{step.name}</code>
                {execution ? (
                  <Status value={execution.status} />
                ) : (
                  <span>{step.checks.length} checks</span>
                )}
              </div>
              <strong>{step.title}</strong>
              <div className="graph-inputs">
                {execution?.status === "successful" && <Check size={11} />}
                <span>← {step.depends_on.join(" · ")}</span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
