"use client";
import { Trans } from "@lingui/react/macro";
import * as React from "react";
import { Dialog as SheetPrimitive } from "@base-ui/react/dialog";
import { cva, type VariantProps } from "class-variance-authority";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

const Sheet = SheetPrimitive.Root;

const SheetTrigger = SheetPrimitive.Trigger;

const SheetClose = React.forwardRef<
  HTMLButtonElement,
  Omit<SheetPrimitive.Close.Props, "render"> & { asChild?: boolean }
>(({ asChild, children, ...props }, ref) => (
  <SheetPrimitive.Close
    ref={ref}
    render={asChild && React.isValidElement(children) ? children : undefined}
    {...props}
  >
    {asChild ? undefined : children}
  </SheetPrimitive.Close>
));
SheetClose.displayName = "SheetClose";

const SheetPortal = SheetPrimitive.Portal;

const SheetOverlay = React.forwardRef<
  HTMLDivElement,
  SheetPrimitive.Backdrop.Props
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Backdrop
    className={cn(
      "fixed inset-0 z-50 bg-black/80 transition-opacity data-starting-style:opacity-0 data-ending-style:opacity-0",
      className,
    )}
    {...props}
    ref={ref}
  />
));
SheetOverlay.displayName = "SheetOverlay";

const sheetVariants = cva(
  "fixed z-50 gap-4 bg-background p-6 shadow-lg transition-[opacity,transform] ease-in-out duration-300 data-starting-style:opacity-0 data-ending-style:opacity-0",
  {
    variants: {
      side: {
        top: "inset-x-0 top-0 border-b data-starting-style:-translate-y-full data-ending-style:-translate-y-full",
        bottom:
          "inset-x-0 bottom-0 border-t data-starting-style:translate-y-full data-ending-style:translate-y-full",
        left: "inset-y-0 left-0 h-full w-3/4 border-r data-starting-style:-translate-x-full data-ending-style:-translate-x-full sm:max-w-sm",
        right:
          "inset-y-0 right-0 h-full w-3/4 border-l data-starting-style:translate-x-full data-ending-style:translate-x-full sm:max-w-sm",
      },
    },
    defaultVariants: {
      side: "right",
    },
  },
);

interface SheetContentProps
  extends SheetPrimitive.Popup.Props, VariantProps<typeof sheetVariants> {}

const SheetContent = React.forwardRef<HTMLDivElement, SheetContentProps>(
  ({ side = "right", className, children, ...props }, ref) => (
    <SheetPortal>
      <SheetOverlay />
      <SheetPrimitive.Popup
        ref={ref}
        className={cn(sheetVariants({ side }), className)}
        {...props}
      >
        <SheetPrimitive.Close className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-popup-open:bg-secondary">
          <X className="h-4 w-4" />
          <span className="sr-only">
            <Trans>Close</Trans>
          </span>
        </SheetPrimitive.Close>
        {children}
      </SheetPrimitive.Popup>
    </SheetPortal>
  ),
);
SheetContent.displayName = "SheetContent";

const SheetHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col space-y-2 text-center sm:text-left",
      className,
    )}
    {...props}
  />
);
SheetHeader.displayName = "SheetHeader";

const SheetFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2",
      className,
    )}
    {...props}
  />
);
SheetFooter.displayName = "SheetFooter";

const SheetTitle = React.forwardRef<
  HTMLHeadingElement,
  SheetPrimitive.Title.Props
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Title
    ref={ref}
    className={cn("text-lg font-semibold text-foreground", className)}
    {...props}
  />
));
SheetTitle.displayName = "SheetTitle";

const SheetDescription = React.forwardRef<
  HTMLParagraphElement,
  SheetPrimitive.Description.Props
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Description
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
));
SheetDescription.displayName = "SheetDescription";

export {
  Sheet,
  SheetPortal,
  SheetOverlay,
  SheetTrigger,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
};
