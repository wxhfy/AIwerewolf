"use client";

import { useCallback, useRef, useState } from "react";
import { DramaticOverlay } from "@/components/game/DramaticOverlay";
import { PhaseAnnouncement, type PhaseAnnouncementProps } from "@/components/game/PhaseAnnouncement";

interface PhaseOverlayCoordinatorProps {
  phaseAnnouncement: PhaseAnnouncementProps | null;
}

/**
 * Ensures DramaticOverlay and PhaseAnnouncement never overlap.
 *
 * Priority: DramaticOverlay (death/elimination) suppresses PhaseAnnouncement
 * until it finishes fading (300ms buffer).
 */
export function PhaseOverlayCoordinator({ phaseAnnouncement }: PhaseOverlayCoordinatorProps) {
  const [dramaticActive, setDramaticActive] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleDramaticChange = useCallback((visible: boolean) => {
    if (visible) {
      setDramaticActive(true);
    } else {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setDramaticActive(false), 300);
    }
  }, []);

  const effectiveAnnouncement =
    phaseAnnouncement && !dramaticActive ? phaseAnnouncement : null;

  return (
    <>
      <DramaticOverlay onVisibilityChange={handleDramaticChange} />
      {effectiveAnnouncement && (
        <PhaseAnnouncement
          group={effectiveAnnouncement.group}
          visible={effectiveAnnouncement.visible}
        />
      )}
    </>
  );
}
