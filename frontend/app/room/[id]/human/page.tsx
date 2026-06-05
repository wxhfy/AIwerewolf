"use client";

import { useEffect } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

/**
 * Redirect /room/[id]/human → /room/[id]/play?mode=human
 *
 * The human game page has been merged into the unified GamePage component.
 * This file exists only as a redirect shim for backward compatibility.
 */
export default function HumanPageRedirect() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    const mode = searchParams.toString()
      ? `human&${searchParams.toString()}`
      : "human";
    router.replace(`/room/${params.id}/play?mode=${mode}`);
  }, [params.id, searchParams, router]);

  return null;
}
