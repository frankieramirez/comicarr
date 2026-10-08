import * as React from "react";
import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow hover:bg-primary/90",
        destructive:
          "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
        outline:
          "border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground",
        secondary:
          "bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2 rounded-md",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-md px-8",
        icon: "h-9 w-9 rounded-md",
        "icon-sm": "size-8 rounded-md",
        compact: "h-7 px-2.5 rounded-[5px] text-[12px] [&_svg]:size-3",
        toolbar: "h-8 px-3 rounded-[5px] text-[12px] [&_svg]:size-3.5",
      },
      mono: {
        true: "font-mono uppercase tracking-[0.05em]",
      },
    },
    compoundVariants: [
      {
        variant: "outline",
        size: "compact",
        class:
          "border-border bg-transparent shadow-none hover:bg-secondary/50 hover:text-foreground",
      },
      {
        variant: "outline",
        size: "toolbar",
        class:
          "border-border bg-transparent shadow-none hover:bg-secondary/50 hover:text-foreground",
      },
    ],
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends ButtonPrimitive.Props, VariantProps<typeof buttonVariants> {
  /** @deprecated Use Base UI's render prop. */
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, mono, asChild, children, ...props }, ref) => {
    return (
      <ButtonPrimitive
        render={asChild ? (children as React.ReactElement) : undefined}
        className={cn(buttonVariants({ variant, size, mono, className }))}
        ref={ref}
        {...props}
      >
        {asChild ? undefined : children}
      </ButtonPrimitive>
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
