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
    const nextParams = new URLSearchParams(searchParams.toString());
    nextParams.set("mode", "human");
    router.replace(`/room/${params.id}/play?${nextParams.toString()}`);
  }, [params.id, searchParams, router]);

  return null;
}
