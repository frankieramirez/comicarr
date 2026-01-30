export function SettingGroup({ title, description, children }) {
  return (
    <fieldset className="border border-gray-200 rounded-lg p-4 mb-6">
      <legend className="text-sm font-semibold text-gray-900 px-2">{title}</legend>
      {description && (
        <p className="text-sm text-gray-500 mb-4">{description}</p>
      )}
      <div className="space-y-4">
        {children}
      </div>
    </fieldset>
  );
}
