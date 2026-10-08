import { useId, useState } from "react";
import { Check } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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

/** Label for a coded select value. Used so the trigger does not wait for the popup to mount. */
export function labelForSelectValue(
  options: SelectOption[],
  value?: string | number,
): string | undefined {
  if (value === undefined || value === null) return undefined;
  const wanted = value.toString();
  return options.find((option) => option.value.toString() === wanted)?.label;
}

interface SettingFieldProps {
  label: string;
  value?: string | number;
  onChange?: (value: string | boolean) => void;
  type?: "text" | "password" | "number" | "checkbox" | "select" | "textarea";
  readOnly?: boolean;
  helpText?: string;
  error?: string;
  options?: SelectOption[];
  checked?: boolean;
  placeholder?: string;
  /** Minimum accepted value. Number fields only. */
  min?: number;
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
  min,
}: SettingFieldProps) {
  const uid = useId();
  const fieldId = uid;
  const helpId = `${uid}-help`;
  const errorId = `${uid}-error`;
  const describedBy =
    [helpText ? helpId : null, error ? errorId : null]
      .filter(Boolean)
      .join(" ") || undefined;
  const testId = `field-${label.toLowerCase().replace(/\s+/g, "-")}`;
  const [checkboxFocused, setCheckboxFocused] = useState(false);

  if (type === "checkbox") {
    return (
      <label
        htmlFor={fieldId}
        className="flex items-start gap-3 py-2.5 px-3 rounded-lg border-[0.5px] cursor-pointer select-none"
        style={{
          borderColor: "var(--border)",
          background: "var(--card)",
        }}
      >
        <input
          id={fieldId}
          data-testid={testId}
          type="checkbox"
          checked={!!checked}
          onChange={(e) => onChange(e.target.checked)}
          onFocus={() => setCheckboxFocused(true)}
          onBlur={() => setCheckboxFocused(false)}
          disabled={readOnly}
          className="sr-only peer"
        />
        <span
          className="mt-0.5 shrink-0 w-4 h-4 rounded-[3px] grid place-items-center border peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-background"
          style={{
            borderColor: checked ? "var(--primary)" : "var(--border)",
            background: checked ? "var(--primary)" : "transparent",
            boxShadow: checkboxFocused
              ? "0 0 0 2px var(--background), 0 0 0 4px var(--ring)"
              : undefined,
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
            <span
              id={helpId}
              className="block text-[11.5px] text-muted-foreground mt-0.5"
            >
              {helpText}
            </span>
          )}
          {error && (
            <span
              id={errorId}
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

  if (readOnly) {
    return (
      <div className="grid gap-2 sm:gap-4 py-3 sm:items-center grid-cols-1 sm:[grid-template-columns:200px_1fr]">
        <div>
          <div className="text-sm font-medium">{label}</div>
          {helpText && (
            <div className="text-xs text-muted-foreground mt-0.5 leading-snug">
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

  if (type === "select") {
    const selectedLabel = labelForSelectValue(options, value);
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
            <SelectTrigger
              id={fieldId}
              data-testid={testId}
              aria-describedby={describedBy}
            >
              <SelectValue placeholder={placeholder || "Select…"}>
                {selectedLabel}
              </SelectValue>
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
          <p id={helpId} className="text-[11px] text-muted-foreground mt-1">
            {helpText}
          </p>
        )}
        {error && (
          <p
            id={errorId}
            className="text-[11px] mt-1"
            style={{ color: "var(--status-error)" }}
          >
            {error}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="py-2.5">
      <Label htmlFor={fieldId} className="text-[12.5px] font-medium">
        {label}
      </Label>
      {type === "textarea" ? (
        <Textarea
          id={fieldId}
          data-testid={testId}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={3}
          aria-describedby={describedBy}
          className="mt-1.5 font-mono"
        />
      ) : (
        <Input
          id={fieldId}
          data-testid={testId}
          type={type}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          min={type === "number" ? min : undefined}
          aria-describedby={describedBy}
          className="mt-1.5"
        />
      )}
      {helpText && (
        <p id={helpId} className="text-[11px] text-muted-foreground mt-1">
          {helpText}
        </p>
      )}
      {error && (
        <p
          id={errorId}
          className="text-[11px] mt-1"
          style={{ color: "var(--status-error)" }}
        >
          {error}
        </p>
      )}
    </div>
  );
}
