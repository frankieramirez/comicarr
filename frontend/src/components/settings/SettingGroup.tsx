interface SettingGroupProps {
  title: string;
  description?: string;
  children: React.ReactNode;
}

export function SettingGroup({ title, description, children }: SettingGroupProps) {
  return (
    <fieldset className="border border-card-border rounded-lg p-4 mb-6">
      <legend className="text-sm font-semibold text-gray-900 px-2">{title}</legend>
      {description && (
        <p className="text-sm text-muted-foreground mb-4">{description}</p>
      )}
      <div className="space-y-4">
        {children}
      </div>
    </fieldset>
  );
}
