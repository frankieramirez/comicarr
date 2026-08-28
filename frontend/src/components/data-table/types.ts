import type { JSX } from "react";

export type SearchParams = {
  [key: string]: string | string[] | undefined;
};

export type DatePreset = {
  label: string;
  from: Date;
  to: Date;
  shortcut: string;
};

export type Option = {
  label: string;
  value: string | boolean | number | undefined;
};

export type Input = {
  type: "input";
  options?: Option[];
};

export type Checkbox = {
  type: "checkbox";
  component?: (props: Option) => JSX.Element | null;
  options?: Option[];
};

export type Slider = {
  type: "slider";
  min: number;
  max: number;
  options?: Option[];
  unit?: string;
};

export type Timerange = {
  type: "timerange";
  options?: Option[]; // required for TS
  presets?: DatePreset[];
};

export type Base<TData> = {
  label: string;
  value: keyof TData;
  /**
   * Defines if the accordion in the filter bar is open by default
   */
  defaultOpen?: boolean;
  /**
   * Defines if the command input is disabled for this field
   */
  commandDisabled?: boolean;
};

export type DataTableCheckboxFilterField<TData> = Base<TData> & Checkbox;
export type DataTableSliderFilterField<TData> = Base<TData> & Slider;
export type DataTableInputFilterField<TData> = Base<TData> & Input;
export type DataTableTimerangeFilterField<TData> = Base<TData> & Timerange;

export type DataTableFilterField<TData> =
  | DataTableCheckboxFilterField<TData>
  | DataTableSliderFilterField<TData>
  | DataTableInputFilterField<TData>
  | DataTableTimerangeFilterField<TData>;

/** ----------------------------------------- */

export type SheetField<TData, TMeta = Record<string, unknown>> = {
  id: keyof TData;
  label: string;
  type: "readonly" | "input" | "checkbox" | "slider" | "timerange";
  display?: { type: string; unit?: string; colorMap?: Record<string, string> };
  component?: (
    props: TData & {
      metadata?: {
        totalRows: number;
        filterRows: number;
        totalRowsFetched: number;
      } & TMeta;
    },
  ) => JSX.Element | null | string;
  condition?: (props: TData) => boolean;
  className?: string;
  skeletonClassName?: string;
};
