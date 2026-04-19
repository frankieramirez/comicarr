import { Check } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface SelectOption {
  value: string | number;
  label: string;
}

interface SettingFieldProps {
  label: string;
  value?: string | number;
  onChange?: (value: string | boolean) => void;
  type?: "text" | "password" | "number" | "checkbox" | "select";
  readOnly?: boolean;
  helpText?: string;
  error?: string;
  options?: SelectOption[];
  checked?: boolean;
  placeholder?: string;
}

export function SettingField({
  label,
  value,
  onChange = () => {},
  type = "text",
  readOnly = false,
  helpText,
  error,
  options = [],
  checked,
  placeholder,
}: SettingFieldProps) {
  const fieldId = `field-${label.toLowerCase().replace(/\s+/g, "-")}`;

  // Checkbox: circular accent check + label + help text + right-aligned spacing
  if (type === "checkbox") {
    return (
      <label
        htmlFor={fieldId}
        className="flex items-start gap-3 py-2.5 px-3 rounded-[6px] border cursor-pointer select-none"
        style={{
          borderColor: "var(--border)",
          background: "var(--card)",
        }}
      >
        <input
          id={fieldId}
          type="checkbox"
          checked={!!checked}
          onChange={(e) => onChange(e.target.checked)}
          disabled={readOnly}
          className="sr-only peer"
        />
        <span
          className="mt-0.5 shrink-0 w-4 h-4 rounded-[3px] grid place-items-center border"
          style={{
            borderColor: checked ? "var(--primary)" : "var(--border)",
            background: checked ? "var(--primary)" : "transparent",
          }}
        >
          {checked && (
            <Check
              className="w-3 h-3"
              strokeWidth={3}
              style={{ color: "var(--primary-foreground)" }}
            />
          )}
        </span>
        <span className="flex-1 min-w-0">
          <span className="block text-[13px] font-medium">{label}</span>
          {helpText && (
            <span className="block text-[11.5px] text-muted-foreground mt-0.5">
              {helpText}
            </span>
          )}
          {error && (
            <span
              className="block text-[11.5px] mt-0.5"
              style={{ color: "var(--status-error)" }}
            >
              {error}
            </span>
          )}
        </span>
      </label>
    );
  }

  // Read-only inline row: label on left, input + tag on right (stacks on mobile)
  if (readOnly) {
    return (
      <div className="grid gap-2 sm:gap-4 py-3 sm:items-center grid-cols-1 sm:[grid-template-columns:200px_1fr]">
        <div>
          <div className="text-[12.5px] font-medium">{label}</div>
          {helpText && (
            <div className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
              {helpText}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 min-w-0">
          <div
            className="flex-1 min-w-0 font-mono text-[12px] px-3 py-1.5 rounded-[5px] border bg-card break-all"
            style={{ borderColor: "var(--border)" }}
          >
            {value ?? "—"}
          </div>
          <span className="font-mono text-[10px] text-muted-foreground shrink-0">
            read-only
          </span>
        </div>
      </div>
    );
  }

  // Select field
  if (type === "select") {
    return (
      <div className="py-2.5">
        <Label htmlFor={fieldId} className="text-[12.5px] font-medium">
          {label}
        </Label>
        <div className="mt-1.5">
          <Select
            value={value?.toString()}
            onValueChange={onChange}
            disabled={readOnly}
          >
            <SelectTrigger id={fieldId}>
              <SelectValue placeholder={placeholder || "Select…"} />
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
        {helpText && (
          <p className="text-[11px] text-muted-foreground mt-1">{helpText}</p>
        )}
        {error && (
          <p
            className="text-[11px] mt-1"
            style={{ color: "var(--status-error)" }}
          >
            {error}
          </p>
        )}
      </div>
    );
  }

  // Text / password / number
  return (
    <div className="py-2.5">
      <Label htmlFor={fieldId} className="text-[12.5px] font-medium">
        {label}
      </Label>
      <Input
        id={fieldId}
        type={type}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="mt-1.5"
      />
      {helpText && (
        <p className="text-[11px] text-muted-foreground mt-1">{helpText}</p>
      )}
      {error && (
        <p
          className="text-[11px] mt-1"
          style={{ color: "var(--status-error)" }}
        >
          {error}
        </p>
      )}
    </div>
  );
}
