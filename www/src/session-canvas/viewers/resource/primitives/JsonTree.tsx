import type { ReactNode } from "react";

/**
 * Collapsible JSON tree shared by the json and native-record viewers. Uses
 * native <details>/<summary> so expand/collapse is keyboard reachable with no
 * custom ARIA. Object/array nodes auto-open for the first two levels; deeper
 * nodes start collapsed so a large record does not explode on open.
 */
export function JsonTree({ value }: { value: unknown }) {
  return (
    <div className="canvas-json-tree">
      <JsonNode value={value} label={null} path="$" depth={0} />
    </div>
  );
}

const MAX_DEPTH = 200;

function JsonNode({
  value,
  label,
  path,
  depth,
}: {
  value: unknown;
  label: string | null;
  path: string;
  depth: number;
}): ReactNode {
  if (depth > MAX_DEPTH) return <Leaf label={label} type="depth" text="…" />;

  if (value === null) return <Leaf label={label} type="null" text="null" />;

  if (Array.isArray(value)) {
    return (
      <Branch label={label} meta={`Array(${value.length})`} open={depth < 2}>
        {value.map((item, index) => {
          // A JSON array element's identity is its position; the path is unique
          // per node and the tree is immutable, so this key is stable.
          const childPath = `${path}[${index}]`;
          return (
            <JsonNode
              key={childPath}
              value={item}
              label={String(index)}
              path={childPath}
              depth={depth + 1}
            />
          );
        })}
      </Branch>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    return (
      <Branch label={label} meta={`Object(${entries.length})`} open={depth < 2}>
        {entries.map(([key, child]) => (
          <JsonNode
            key={`${path}.${key}`}
            value={child}
            label={key}
            path={`${path}.${key}`}
            depth={depth + 1}
          />
        ))}
      </Branch>
    );
  }

  const text = typeof value === "string" ? JSON.stringify(value) : String(value);
  return <Leaf label={label} type={typeof value} text={text} />;
}

function Branch({
  label,
  meta,
  open,
  children,
}: {
  label: string | null;
  meta: string;
  open: boolean;
  children: ReactNode;
}) {
  return (
    <details className="canvas-json-branch" open={open}>
      <summary className="canvas-json-summary">
        {label !== null && <span className="canvas-json-key">{label}</span>}
        <span className="canvas-json-meta">{meta}</span>
      </summary>
      <div className="canvas-json-children">{children}</div>
    </details>
  );
}

function Leaf({ label, type, text }: { label: string | null; type: string; text: string }) {
  return (
    <div className="canvas-json-leaf">
      {label !== null && <span className="canvas-json-key">{label}</span>}
      <span className="canvas-json-value" data-type={type}>
        {text}
      </span>
    </div>
  );
}
