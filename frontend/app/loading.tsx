import { Skeleton } from "@/components/ui/Feedback";

export default function Loading() {
  return (
    <main data-theme="dark" role="status" aria-label="正在加载大厅 / Loading lobby" className="flex min-h-[100dvh] flex-col items-center bg-background px-4 pb-8 pt-24 text-textPrimary sm:pt-20">
      <span className="sr-only">正在加载大厅 / Loading lobby</span>
      <div aria-hidden="true" className="flex w-full max-w-lg flex-col items-center">
        <Skeleton className="mb-5 h-10 w-10 rounded-full" />
        <Skeleton className="h-10 w-56" />
        <Skeleton className="mb-8 mt-4 h-4 w-64 max-w-full" />
        <div className="w-full space-y-6 rounded-card border border-border bg-cardBackground p-5 shadow-card sm:p-7">
          <Skeleton className="h-6 w-36" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-4 w-4/5" />
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-11" />)}
          </div>
          <Skeleton className="h-12 w-full" />
          <Skeleton className="mx-auto h-3 w-3/4" />
        </div>
      </div>
    </main>
  );
}
