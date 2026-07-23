import { useCallback, useRef, useState } from "react";
import { GripVertical, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import { MIN_HEIGHT, PANEL_COLUMNS, usePanelLayout } from "@/hooks/usePanelLayout";
import { ResizeHandle } from "./ResizeHandle";

export type BoardSection = {
  id: string;
  title: string;
  /** Columns out of 12 this section occupies before the user customises it. */
  defaultSpan?: number;
  icon?: React.ComponentType<{ className?: string }>;
  content: React.ReactNode;
};

type SectionBoardProps = {
  /** Stable key the saved layout is stored under. */
  layoutId: string;
  sections: BoardSection[];
  className?: string;
};

/**
 * A dashboard of page sections the user can drag to reorder and drag to resize.
 *
 * Sizes are kept in 12-column units horizontally and pixels vertically, and the
 * arrangement is persisted per `layoutId`, so a user's preferred workspace
 * survives navigation and reloads.
 */
export function SectionBoard({ layoutId, sections, className }: SectionBoardProps) {
  const ids = sections.map((section) => section.id);
  const { order, sizes, move, resize, reset, isCustomised } = usePanelLayout(layoutId, ids);
  const gridRef = useRef<HTMLDivElement>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);

  const byId = new Map(sections.map((section) => [section.id, section]));
  const ordered = order.map((id) => byId.get(id)).filter(Boolean) as BoardSection[];

  const columnWidth = useCallback(() => {
    const width = gridRef.current?.clientWidth ?? 0;
    return width > 0 ? width / PANEL_COLUMNS : 96;
  }, []);

  const handleResize = useCallback(
    (section: BoardSection, delta: { x: number; y: number }) => {
      const current = sizes[section.id] ?? {};
      const span = current.span ?? section.defaultSpan ?? PANEL_COLUMNS;
      const height = current.height ?? MIN_HEIGHT * 2;
      const patch: { span?: number; height?: number } = {};
      if (delta.x !== 0) patch.span = span + delta.x / columnWidth();
      if (delta.y !== 0) patch.height = height + delta.y;
      resize(section.id, patch);
    },
    [columnWidth, resize, sizes],
  );

  return (
    <div className={cn("space-y-2", className)}>
      {isCustomised && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={reset}
            className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <RotateCcw className="h-3 w-3" />
            Reset layout
          </button>
        </div>
      )}

      <div ref={gridRef} className="grid grid-cols-12 gap-4 items-start">
        {ordered.map((section) => {
          const size = sizes[section.id] ?? {};
          const span = Math.round(size.span ?? section.defaultSpan ?? PANEL_COLUMNS);
          const isDragging = draggingId === section.id;
          const isDropTarget = dropTargetId === section.id && draggingId !== section.id;

          return (
            <section
              key={section.id}
              style={{ gridColumn: `span ${span} / span ${span}` }}
              onDragOver={(event) => {
                if (!draggingId) return;
                event.preventDefault();
                setDropTargetId(section.id);
              }}
              onDragLeave={() => setDropTargetId((current) => (current === section.id ? null : current))}
              onDrop={(event) => {
                event.preventDefault();
                if (draggingId) move(draggingId, section.id);
                setDraggingId(null);
                setDropTargetId(null);
              }}
              className={cn(
                "group/section relative rounded-lg border bg-card transition-shadow",
                isDragging && "opacity-50",
                isDropTarget && "ring-2 ring-primary/60",
              )}
            >
              <header
                draggable
                onDragStart={(event) => {
                  setDraggingId(section.id);
                  event.dataTransfer.effectAllowed = "move";
                  // Firefox requires data to be set for a drag to start.
                  event.dataTransfer.setData("text/plain", section.id);
                }}
                onDragEnd={() => {
                  setDraggingId(null);
                  setDropTargetId(null);
                }}
                className="flex cursor-grab items-center gap-2 border-b px-3 py-2 active:cursor-grabbing"
              >
                <GripVertical className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
                {section.icon && <section.icon className="h-4 w-4 shrink-0 text-muted-foreground" />}
                <h3 className="truncate text-sm font-medium">{section.title}</h3>
                <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">
                  {span}/{PANEL_COLUMNS}
                </span>
              </header>

              <div
                className="overflow-auto p-3"
                style={size.height ? { height: size.height } : undefined}
              >
                {section.content}
              </div>

              {/* width */}
              <ResizeHandle
                axis="x"
                label={`Resize ${section.title} width`}
                onResize={(delta) => handleResize(section, { x: delta.x, y: 0 })}
                className="absolute inset-y-0 -right-2 flex w-4 items-center group-hover/section:opacity-100"
              />
              {/* height */}
              <ResizeHandle
                axis="y"
                label={`Resize ${section.title} height`}
                onResize={(delta) => handleResize(section, { x: 0, y: delta.y })}
                className="absolute inset-x-0 -bottom-2 flex h-4 justify-center group-hover/section:opacity-100"
              />
              {/* corner */}
              <ResizeHandle
                axis="both"
                label={`Resize ${section.title}`}
                onResize={(delta) => handleResize(section, delta)}
                className="absolute -bottom-1 -right-1 flex h-3 w-3 items-center justify-center group-hover/section:opacity-100"
              />
            </section>
          );
        })}
      </div>
    </div>
  );
}
