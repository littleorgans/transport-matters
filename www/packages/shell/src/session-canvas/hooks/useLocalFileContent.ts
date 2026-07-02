import { useQuery } from "@tanstack/react-query";
import { loadLocalFileContent, type ResourceContentResponse } from "../api/resourceContent";

/** Typed missing responses arrive as 200s, so retries only delay the verdict. */
export function useLocalFileContent(path: string) {
  return useQuery<ResourceContentResponse>({
    queryKey: ["local-file", path],
    queryFn: () => loadLocalFileContent(path),
    retry: false,
  });
}
