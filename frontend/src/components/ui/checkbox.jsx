import React from 'react';

export const Checkbox = React.forwardRef(
  ({ checked, onChange, disabled, className = '', indeterminate, ...props }, ref) => {
    const checkboxRef = React.useRef(null);
    const combinedRef = ref || checkboxRef;

    React.useEffect(() => {
      if (combinedRef.current) {
        combinedRef.current.indeterminate = indeterminate || false;
      }
    }, [indeterminate, combinedRef]);

    return (
      <input
        ref={combinedRef}
        type="checkbox"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        className={`
          h-4 w-4 rounded border-input text-primary
          focus:ring-2 focus:ring-primary focus:ring-offset-0
          disabled:cursor-not-allowed disabled:opacity-50
          cursor-pointer
          ${className}
        `}
        {...props}
      />
    );
  }
);

Checkbox.displayName = 'Checkbox';
