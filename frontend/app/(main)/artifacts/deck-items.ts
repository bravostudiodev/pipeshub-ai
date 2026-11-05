import { isPresentationArchive, presentationTitle } from '@/app/components/file-preview/presentation';
import type { ArtifactListItem } from './types';

export function isDeckItem(item: ArtifactListItem): boolean {
  return isPresentationArchive({ fileName: item.name, mimeType: item.mimeType || undefined, artifactType: item.artifactType });
}

/** A deck is shown by its title, never as `….zip`. */
export function artifactDisplayName(item: ArtifactListItem): string {
  return isDeckItem(item) ? presentationTitle(item.name) : item.name;
}
