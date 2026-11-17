import { t } from "@lingui/core/macro";
import { useLocation } from "react-router-dom";
import { Compass } from "lucide-react";
import EmptyState from "@/components/ui/EmptyState";

/**
 * Shown for any app URL that matches no route. It keeps the address the
 * user tried visible, so a stale bookmark or a typo is obvious instead of
 * silently landing on the dashboard (#1496).
 */
export default function NotFoundPage() {
  const location = useLocation();
  const path = `${location.pathname}${location.search}`;
  return (
    <EmptyState
      icon={Compass}
      eyebrow={t`NOT FOUND`}
      title={t`This page doesn't exist`}
      description={t`Nothing in Comicarr lives at ${path}. The link may be old or mistyped.`}
      action={{ label: t`Go to the dashboard`, to: "/" }}
    />
  );
}
