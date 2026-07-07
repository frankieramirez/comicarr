import { useConfig } from "@/hooks/useConfig";

export function useContentSources() {
  const { data: config } = useConfig();
  return {
    comicsEnabled: config?.comicvine_enabled ?? true,
    comicsConfigured:
      (config?.comicvine_api_set as boolean | undefined) ?? false,
    mangaEnabled:
      (config?.mangadex_enabled ?? false) ||
      (config?.mal_enabled as boolean | undefined) === true,
    isLoaded: !!config,
  };
}
