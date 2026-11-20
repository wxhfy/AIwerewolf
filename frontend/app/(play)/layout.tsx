import React from "react";

export default function PlayLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="relative min-h-screen [min-height:100dvh] w-full overflow-x-hidden bg-background text-textPrimary">
      {children}
    </div>
  );
}
