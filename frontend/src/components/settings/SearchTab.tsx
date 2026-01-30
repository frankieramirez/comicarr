import { SettingGroup } from './SettingGroup';
import { SettingField } from './SettingField';

interface SearchTabProps {
  config: Record<string, unknown>;
  formData: Record<string, unknown>;
  onChange: (key: string, value: string | boolean | number) => void;
}

export function SearchTab({ formData, onChange }: SearchTabProps) {
  const qualityOptions = [
    { value: '0', label: 'Any Quality' },
    { value: '1', label: 'HD Only' },
    { value: '2', label: 'Web-DL Only' },
  ];

  return (
    <div className="space-y-6">
      <SettingGroup
        title="Quality Settings"
        description="Configure preferred quality for downloads"
      >
        <SettingField
          label="Preferred Quality"
          value={String(formData.preferred_quality ?? '')}
          type="select"
          options={qualityOptions}
          onChange={(value) => onChange('preferred_quality', parseInt(value as string))}
          helpText="Filter search results by quality preference"
        />
      </SettingGroup>

      <SettingGroup
        title="File Size Constraints"
        description="Set minimum and maximum file size limits for downloads"
      >
        <SettingField
          label="Enable Minimum Size"
          type="checkbox"
          checked={formData.use_minsize as boolean | undefined}
          onChange={(checked) => onChange('use_minsize', checked as boolean)}
          helpText="Reject downloads smaller than the minimum size"
        />
        {Boolean(formData.use_minsize) && (
          <SettingField
            label="Minimum Size (MB)"
            value={formData.minsize as number | undefined}
            type="number"
            onChange={(value) => onChange('minsize', value as string)}
            placeholder="e.g., 10"
            helpText="Minimum file size in megabytes"
          />
        )}
        <SettingField
          label="Enable Maximum Size"
          type="checkbox"
          checked={formData.use_maxsize as boolean | undefined}
          onChange={(checked) => onChange('use_maxsize', checked as boolean)}
          helpText="Reject downloads larger than the maximum size"
        />
        {Boolean(formData.use_maxsize) && (
          <SettingField
            label="Maximum Size (MB)"
            value={formData.maxsize as number | undefined}
            type="number"
            onChange={(value) => onChange('maxsize', value as string)}
            placeholder="e.g., 500"
            helpText="Maximum file size in megabytes"
          />
        )}
      </SettingGroup>
    </div>
  );
}
