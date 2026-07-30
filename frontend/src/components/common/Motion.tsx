import { Children, cloneElement, isValidElement, type CSSProperties, type ElementType, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { useReveal } from "@/hooks/useMotion";

// ---------------------------------------------------------------------------
// Presentation primitives for the editorial motion language:
//   Reveal      — one-way scroll-in for a block
//   Stagger     — same, but each child trails the one before it
//   SplitLines  — headline that resolves line by line
//   Eyebrow     — uppercase mono micro-label
//   SectionMark — the numbered "01." rule that opens a section
//
// The cursor-tracked spotlight is deliberately NOT here: `.spotlight` is a
// plain class driven by one delegated listener in lib/spotlight.ts, so it
// works on any surface without that surface having to be a component.
// ---------------------------------------------------------------------------

interface RevealProps {
  children: ReactNode;
  /** Milliseconds to hold before this block starts resolving. */
  delay?: number;
  /** `rise` lifts from below, `fade` resolves in place, `wipe` slides from the inline start. */
  variant?: "rise" | "fade" | "wipe";
  className?: string;
  as?: ElementType;
}

export function Reveal({ children, delay = 0, variant = "rise", className, as: Tag = "div" }: RevealProps) {
  const { ref, shown } = useReveal<HTMLDivElement>();
  return (
    <Tag
      ref={ref}
      className={cn("reveal", `reveal-${variant}`, shown && "is-shown", className)}
      style={{ "--reveal-delay": `${delay}ms` } as CSSProperties}
    >
      {children}
    </Tag>
  );
}

interface StaggerProps {
  children: ReactNode;
  /** Gap between consecutive children, in milliseconds. */
  step?: number;
  delay?: number;
  variant?: RevealProps["variant"];
  className?: string;
  as?: ElementType;
}

/**
 * Reveals its children in sequence off a single observer, so a grid of cards
 * costs one IntersectionObserver rather than one per card.
 *
 * The reveal classes are merged onto each child directly rather than added via
 * a wrapper element: a wrapper would either break the parent grid's column
 * placement, or (if given `display: contents`) be unable to animate at all,
 * since transform and opacity have no effect on a contents box.
 */
export function Stagger({ children, step = 60, delay = 0, variant = "rise", className, as: Tag = "div" }: StaggerProps) {
  const { ref, shown } = useReveal<HTMLDivElement>();
  return (
    <Tag ref={ref} className={cn(className)}>
      {Children.map(children, (child, index) => {
        if (!isValidElement<{ className?: string; style?: CSSProperties }>(child)) return child;
        return cloneElement(child, {
          className: cn("reveal", `reveal-${variant}`, shown && "is-shown", child.props.className),
          style: {
            ...child.props.style,
            "--reveal-delay": `${delay + index * step}ms`,
          } as CSSProperties,
        });
      })}
    </Tag>
  );
}

/**
 * Headline that resolves one line at a time. Pass lines as separate strings —
 * splitting on `<br>` would fight the reveal because each line needs to be its
 * own overflow-clipped box.
 */
export function SplitLines({
  lines,
  className,
  lineClassName,
  step = 110,
  delay = 0,
}: {
  lines: ReactNode[];
  className?: string;
  lineClassName?: string;
  step?: number;
  delay?: number;
}) {
  const { ref, shown } = useReveal<HTMLHeadingElement>({ threshold: 0.2 });
  return (
    <span ref={ref} className={cn("block", className)}>
      {lines.map((line, index) => (
        <span key={index} className="split-line">
          <span
            className={cn("split-line-inner", shown && "is-shown", lineClassName)}
            style={{ "--reveal-delay": `${delay + index * step}ms` } as CSSProperties}
          >
            {line}
          </span>
        </span>
      ))}
    </span>
  );
}

/** Uppercase mono micro-label — the "third voice" both references rely on. */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("eyebrow", className)}>{children}</p>;
}

/** Numbered section opener: `01.` followed by a rule that draws itself in. */
export function SectionMark({
  index,
  title,
  hint,
  className,
}: {
  index: number;
  title: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  const { ref, shown } = useReveal<HTMLDivElement>({ threshold: 0.4 });
  return (
    <div ref={ref} className={cn("section-mark", shown && "is-shown", className)}>
      <span className="section-mark-index">{String(index).padStart(2, "0")}.</span>
      <h2 className="section-mark-title">{title}</h2>
      <span className="section-mark-rule" aria-hidden="true" />
      {hint && <span className="section-mark-hint">{hint}</span>}
    </div>
  );
}
