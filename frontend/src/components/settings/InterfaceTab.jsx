import { SettingGroup } from './SettingGroup';
import { SettingField } from './SettingField';

export function InterfaceTab({ config, formData, onChange }) {
  const interfaceOptions = [
    { value: 'carbon', label: 'Carbon (Modern)' },
    { value: 'default', label: 'Default (Classic)' },
  ];

  return (
    <div className="space-y-6">
      <SettingGroup
        title="Server Settings"
        description="Basic server configuration (read-only, modify in config.ini)"
      >
        <SettingField
          label="Host"
          value={config.http_host}
          type="text"
          readOnly
          helpText="IP address the server listens on"
        />
        <SettingField
          label="Port"
          value={config.http_port}
          type="number"
          readOnly
          helpText="Port number for web interface"
        />
        <SettingField
          label="Username"
          value={config.http_username}
          type="text"
          readOnly
          helpText="HTTP authentication username"
        />
      </SettingGroup>

      <SettingGroup
        title="Interface Preferences"
        description="Customize the look and behavior of the web interface"
      >
        <SettingField
          label="Theme"
          value={formData.interface}
          type="select"
          options={interfaceOptions}
          onChange={(value) => onChange('interface', value)}
          helpText="Choose your preferred interface theme"
        />
        <SettingField
          label="Launch Browser"
          type="checkbox"
          checked={formData.launch_browser}
          onChange={(checked) => onChange('launch_browser', checked)}
          helpText="Automatically open browser when Mylar starts"
        />
      </SettingGroup>
    </div>
  );
}
