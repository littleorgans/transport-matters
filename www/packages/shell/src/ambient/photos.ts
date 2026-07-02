/**
 * Photo catalog for the Photo study scene.
 *
 * Two sources:
 * 1. LOCAL — drop image files into `src/photos/` and they appear in the
 *    photo selector automatically (Vite glob; dev server picks up new files
 *    live). Add credits in `src/photos/credits.json`, keyed by filename:
 *      { "my-photo.jpg": { "author": "Jane Doe", "url": "https://unsplash.com/photos/abc123" } }
 * 2. PICSUM — placeholder set mirroring Unsplash photography; author and
 *    source page are fetched at runtime so attribution is always real.
 *
 * When this graduates to the Unsplash API: image URLs come from the API
 * response, attribution links carry UTM params, and each use must ping the
 * photo's download endpoint per Unsplash guidelines.
 */
export interface PhotoCredit {
  author: string;
  url: string;
}

export interface PhotoEntry {
  key: string;
  label: string;
  imageUrl: string;
  source: "local" | "picsum";
  picsumId?: string;
  credit?: PhotoCredit;
}

const localImages = import.meta.glob<string>(
  "../photos/*.{jpg,jpeg,png,webp,avif,JPG,JPEG,PNG,WEBP,AVIF}",
  { eager: true, import: "default", query: "?url" },
);

const creditFiles = import.meta.glob<Record<string, Partial<PhotoCredit>>>(
  "../photos/credits.json",
  { eager: true, import: "default" },
);

const credits = Object.values(creditFiles)[0] ?? {};

const basename = (path: string) => path.split("/").pop() ?? path;

const localEntries: PhotoEntry[] = Object.entries(localImages)
  .sort(([a], [b]) => a.localeCompare(b))
  .map(([path, url]) => {
    const name = basename(path);
    const credit = credits[name];
    return {
      key: `local:${name}`,
      label: name.replace(/\.[^.]+$/, ""),
      imageUrl: url,
      source: "local",
      credit:
        credit?.author && credit?.url ? { author: credit.author, url: credit.url } : undefined,
    };
  });

const PICSUM_IDS = ["102", "103", "110", "111", "112", "116"];

const picsumEntries: PhotoEntry[] = PICSUM_IDS.map((id) => ({
  key: `picsum:${id}`,
  label: `Study ${id}`,
  imageUrl: `https://picsum.photos/id/${id}/1920/1080`,
  source: "picsum",
  picsumId: id,
}));

export const photoCatalog: PhotoEntry[] = [...localEntries, ...picsumEntries];

export const photoInfoUrl = (id: string) => `https://picsum.photos/id/${id}/info`;

export const ATTRIBUTION_UTM = "?utm_source=littleorgans&utm_medium=referral";
