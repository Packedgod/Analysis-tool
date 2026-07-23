import { useCallback, useRef } from "react";
import { cn } from "@/lib/utils";

type Axis = "x" | "y" | "both";

type ResizeHandleProps = {
  /** "x" resizes width, "y" resizes height, "both" is the corner grip. */
  axis: Axis;
  /** Called with the pointer delta in pixels since the last move. */
  onResize: (delta: { x: number; y: number }) => void;
  onResizeEnd?: () => void;
  /** Keyboard step in pixels. */
  step?: number;
  label: string;
  className?: string;
};

/**
 * A pointer- and keyboard-driven resize grip.
 *
 * Uses pointer capture so a fast drag never "escapes" the handle, and exposes
 * arrow-key resizing with role="separator" so the layout stays operable without
 * a mouse.
 */
export function ResizeHandle({ axis, onResize, onResizeEnd, step = 24, label, className }: ResizeHandleProps) {
  const last = useRef<{ x: number; y: number } | null>(null);

  const handlePointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    last.current = { x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
  }, []);

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!last.current) return;
      const delta = { x: event.clientX - last.current.x, y: event.clientY - last.current.y };
      last.current = { x: event.clientX, y: event.clientY };
      onResize(delta);
    },
    [onResize],
  );

  const endDrag = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!last.current) return;
      last.current = null;
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      onResizeEnd?.();
    },
    [onResizeEnd],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const map: Record<string, { x: number; y: number }> = {
        ArrowLeft: { x: -step, y: 0 },
        ArrowRight: { x: step, y: 0 },
        ArrowUp: { x: 0, y: -step },
        ArrowDown: { x: 0, y: step },
      };
      const delta = map[event.key];
      if (!delta) return;
      if (axis === "x" && delta.x === 0) return;
      if (axis === "y" && delta.y === 0) return;
      event.preventDefault();
      onResize(delta);
      onResizeEnd?.();
    },
    [axis, onResize, onResizeEnd, step],
  );

  return (
    <div
      role="separator"
      aria-label={label}
      aria-orientation={axis === "y" ? "horizontal" : "vertical"}
      tabIndex={0}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={handleKeyDown}
      className={cn(
        "group/handle touch-none select-none opacity-0 transition-opacity",
        "focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
        axis === "x" && "cursor-col-resize",
        axis === "y" && "cursor-row-resize",
        axis === "both" && "cursor-nwse-resize",
        className,
      )}
    >
      <div
        className={cn(
          "rounded-full bg-primary/50 transition-colors group-hover/handle:bg-primary",
          axis === "x" && "mx-auto h-10 w-1",
          axis === "y" && "my-auto h-1 w-10",
          axis === "both" && "h-2 w-2",
        )}
      />
    </div>
  );
}
