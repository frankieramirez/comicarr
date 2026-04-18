interface SettingGroupProps {
  title: string;
  description?: string;
  children: React.ReactNode;
}

export function SettingGroup({
  title,
  description,
  children,
}: SettingGroupProps) {
  return (
    <section className="mb-8">
      <div className="mb-4">
        <div className="text-[13px] font-semibold tracking-tight text-foreground">
          {title}
        </div>
        {description && (
          <div className="text-[12px] text-muted-foreground mt-0.5 leading-relaxed">
            {description}
          </div>
        )}
      </div>
      <div className="space-y-1">{children}</div>
    </section>
  );
}
