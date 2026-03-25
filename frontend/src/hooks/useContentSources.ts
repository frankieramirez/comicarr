import { useConfig } from "@/hooks/useConfig";

export function useContentSources() {
  const { data: config } = useConfig();
  return {
    comicsEnabled: config?.comicvine_enabled ?? true,
    mangaEnabled: config?.mangadex_enabled ?? false,
    isLoaded: !!config,
  };
}
