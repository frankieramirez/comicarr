interface IssueCountCellProps {
  have: number;
  total: number;
}

export function IssueCountCell({ have, total }: IssueCountCellProps) {
  return (
    <div className="text-center font-mono">
      <span className="font-medium">{have}</span>
      <span className="text-muted-foreground"> / {total}</span>
    </div>
  );
}
