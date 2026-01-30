import { SettingGroup } from './SettingGroup';
import { SettingField } from './SettingField';

export function SearchTab({ config, formData, onChange }) {
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
          value={formData.preferred_quality?.toString()}
          type="select"
          options={qualityOptions}
          onChange={(value) => onChange('preferred_quality', parseInt(value))}
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
          checked={formData.use_minsize}
          onChange={(checked) => onChange('use_minsize', checked)}
          helpText="Reject downloads smaller than the minimum size"
        />
        {formData.use_minsize && (
          <SettingField
            label="Minimum Size (MB)"
            value={formData.minsize}
            type="number"
            onChange={(value) => onChange('minsize', value)}
            placeholder="e.g., 10"
            helpText="Minimum file size in megabytes"
          />
        )}
        <SettingField
          label="Enable Maximum Size"
          type="checkbox"
          checked={formData.use_maxsize}
          onChange={(checked) => onChange('use_maxsize', checked)}
          helpText="Reject downloads larger than the maximum size"
        />
        {formData.use_maxsize && (
          <SettingField
            label="Maximum Size (MB)"
            value={formData.maxsize}
            type="number"
            onChange={(value) => onChange('maxsize', value)}
            placeholder="e.g., 500"
            helpText="Maximum file size in megabytes"
          />
        )}
      </SettingGroup>
    </div>
  );
}
