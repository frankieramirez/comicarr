import { useConfig } from "@/hooks/useConfig";

export function useContentSources() {
  const { data: config } = useConfig();
  const cvKey = config?.comicvine_api as string | undefined;
  return {
    comicsEnabled: config?.comicvine_enabled ?? true,
    comicsConfigured: !!(cvKey && cvKey.length > 0),
    mangaEnabled: config?.mangadex_enabled ?? false,
    isLoaded: !!config,
  };
}
