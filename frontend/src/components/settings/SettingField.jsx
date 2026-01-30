import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export function SettingField({
  label,
  value,
  onChange,
  type = 'text',
  readOnly = false,
  helpText,
  error,
  options = [],
  checked,
  placeholder,
}) {
  const fieldId = `field-${label.toLowerCase().replace(/\s+/g, '-')}`;

  const renderField = () => {
    if (type === 'checkbox') {
      return (
        <div className="flex items-center space-x-2">
          <Checkbox
            id={fieldId}
            checked={checked}
            onCheckedChange={onChange}
            disabled={readOnly}
          />
          <Label htmlFor={fieldId} className="text-sm font-medium cursor-pointer">
            {label}
          </Label>
        </div>
      );
    }

    if (type === 'select') {
      return (
        <div className="space-y-2">
          <Label htmlFor={fieldId} className="text-sm font-medium">
            {label}
          </Label>
          <Select
            value={value?.toString()}
            onValueChange={onChange}
            disabled={readOnly}
          >
            <SelectTrigger id={fieldId} className={readOnly ? 'bg-gray-50' : ''}>
              <SelectValue placeholder={placeholder || 'Select...'} />
            </SelectTrigger>
            <SelectContent>
              {options.map((option) => (
                <SelectItem key={option.value} value={option.value.toString()}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      );
    }

    return (
      <div className="space-y-2">
        <Label htmlFor={fieldId} className="text-sm font-medium">
          {label}
        </Label>
        <Input
          id={fieldId}
          type={type}
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          readOnly={readOnly}
          placeholder={placeholder}
          className={readOnly ? 'bg-gray-50' : ''}
        />
      </div>
    );
  };

  return (
    <div className="space-y-1">
      {renderField()}
      {helpText && (
        <p className="text-xs text-gray-500">{helpText}</p>
      )}
      {error && (
        <p className="text-xs text-red-600">{error}</p>
      )}
    </div>
  );
}
