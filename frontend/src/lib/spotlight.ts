import { prefersReducedMotion } from "@/hooks/useMotion";

// ---------------------------------------------------------------------------
// Cursor-tracked spotlight, delegated.
//
// Any element carrying the `.spotlight` class gets a radial highlight that
// follows the pointer. This is deliberately ONE document-level listener rather
// than a hook per card: `.spotlight` is applied as a plain class across many
// surfaces (including ones rendered from data arrays), and per-element effects
// would both multiply listeners and silently do nothing wherever the class was
// used without the matching hook.
//
// The handler writes CSS custom properties only — it never touches React
// state, so pointer movement costs no re-renders.
// ---------------------------------------------------------------------------

let active: HTMLElement | null = null;

// Handled synchronously rather than deferred into requestAnimationFrame:
// pointermove is already coalesced to the frame rate by the browser, and an
// rAF hop would leave the highlight unpainted wherever rAF is throttled (a
// backgrounded or non-compositing tab), which is exactly when the deferred
// callback never runs and the effect silently disappears.
function onPointerMove(event: PointerEvent) {
  const target = (event.target as Element | null)?.closest?.(".spotlight") as HTMLElement | null;

  if (target !== active) {
    active?.style.removeProperty("--spot-on");
    active = target;
    active?.style.setProperty("--spot-on", "1");
  }
  if (!active) return;

  const rect = active.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  active.style.setProperty("--mx", `${((event.clientX - rect.left) / rect.width) * 100}%`);
  active.style.setProperty("--my", `${((event.clientY - rect.top) / rect.height) * 100}%`);
}

function clear() {
  active?.style.removeProperty("--spot-on");
  active = null;
}

/** Call once at startup. Safe to call again; listeners are not duplicated. */
export function initSpotlight() {
  if (typeof document === "undefined" || prefersReducedMotion()) return;
  document.removeEventListener("pointermove", onPointerMove);
  document.addEventListener("pointermove", onPointerMove, { passive: true });
  // A pointer that leaves the window never emits a final move over a non-card,
  // so the last hovered surface would stay lit without this.
  document.addEventListener("pointerleave", clear);
  window.addEventListener("blur", clear);
}
