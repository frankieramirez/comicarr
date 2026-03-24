interface ProgressBarCellProps {
  percentage: number;
}

export function ProgressBarCell({ percentage }: ProgressBarCellProps) {
  return (
    <div className="flex items-center gap-3">
      <div className="w-20 bg-border rounded-full h-1.5 overflow-hidden">
        <div
          className="h-full rounded-full transition-all bg-gradient-to-r from-[#FF5C00] to-[#FF8A4C]"
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className="text-xs text-muted-foreground min-w-[3rem] font-mono">
        {percentage}%
      </span>
    </div>
  );
}
