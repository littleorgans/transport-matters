import { DndContext, MeasuringStrategy, useSensor, useSensors } from "@dnd-kit/core";
import { rectSortingStrategy, SortableContext } from "@dnd-kit/sortable";
import { useEffect, useMemo } from "react";
import { createPlannerRectMeasure, createWorldSpaceCollision } from "./dndSpace";
import { paneDragCursorMode, setPaneDragCursor } from "./dragCursor";
import { useDropTargetStore } from "./dropTargetStore";
import { createPaneDndCallbacks, deliveryTargetAt, type PaneDndDeps } from "./paneDndCallbacks";
import { PaneDragPointerSensor } from "./paneDragPointerSensor";

// The pane reorder DndContext (doc 19): Stuart's sortable-container-in-a-grid
// shape with every coordinate in world space. Both measuring halves read the
// planner store (createPlannerRectMeasure), so dnd-kit never measures the DOM
// and the geometry is frozen mid-drag by construction; collision converts the
// pointer through the viewport. Activation lives in PaneDragPointerSensor:
// 5px distance keeps clicks inert, Shift stays with the canvas pan, resize
// handles stay with @use-gesture.
export interface CanvasPaneDndProps {
  // Stable object (useMemo in the caller): getState-style closures plus the
  // store's commitReorder action.
  deps: PaneDndDeps;
  // Open panes in committed order, minus the expanded hero (side column only
  // sorts in expanded mode; the hero stays a delivery target via the store
  // hit-test, never a reorder target).
  sortablePaneIds: string[];
  // Drag lifecycle for the settle machinery (useReorderSettle): active on
  // lift, settled with the onDragEnd/onDragCancel verdict.
  onDragActiveChange(active: boolean): void;
  onDragSettled(settle: boolean): void;
  children: React.ReactNode;
}

const ACTIVATION_DISTANCE_PX = 5;

export function CanvasPaneDnd({
  deps,
  sortablePaneIds,
  onDragActiveChange,
  onDragSettled,
  children,
}: CanvasPaneDndProps) {
  const sensors = useSensors(
    useSensor(PaneDragPointerSensor, {
      activationConstraint: { distance: ACTIVATION_DISTANCE_PX },
    }),
  );
  const callbacks = useMemo(() => createPaneDndCallbacks(deps), [deps]);
  const measuring = useMemo(() => {
    const measure = createPlannerRectMeasure(deps.getLayout);
    return {
      draggable: { measure },
      droppable: { strategy: MeasuringStrategy.WhileDragging, measure },
    };
  }, [deps]);
  // Unmount safety: never strand the body cursor attribute mid-drag.
  useEffect(() => () => setPaneDragCursor(null), []);

  const collisionDetection = useMemo(
    () =>
      createWorldSpaceCollision({
        getViewport: () => deps.getLayout().viewport,
        getSurfaceOrigin: deps.getSurfaceOrigin,
        getDeliveryTarget: (world, activeId) =>
          deliveryTargetAt(deps.getLayout(), world, activeId, deps.contentRefFor),
      }),
    [deps],
  );

  return (
    <DndContext
      autoScroll={false}
      collisionDetection={collisionDetection}
      measuring={measuring}
      onDragCancel={() => {
        setPaneDragCursor(null);
        onDragSettled(callbacks.onDragCancel().settle);
      }}
      onDragEnd={(event) => {
        setPaneDragCursor(null);
        onDragSettled(callbacks.onDragEnd(event).settle);
      }}
      onDragMove={(event) => {
        callbacks.onDragMove(event);
        // the callbacks just wrote the drop target; project it onto the cursor
        setPaneDragCursor(paneDragCursorMode(useDropTargetStore.getState().target));
      }}
      onDragStart={(event) => {
        callbacks.onDragStart(event);
        onDragActiveChange(true);
        setPaneDragCursor("move");
      }}
      sensors={sensors}
    >
      <SortableContext items={sortablePaneIds} strategy={rectSortingStrategy}>
        {children}
      </SortableContext>
    </DndContext>
  );
}
