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
        <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
        {description && (
          <div className="mt-0.5 text-[13px] leading-relaxed text-foreground-2">
            {description}
          </div>
        )}
      </div>
      <div className="space-y-2">{children}</div>
    </section>
  );
}
