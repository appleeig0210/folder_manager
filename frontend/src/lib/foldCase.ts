/**
 * Fold a tag into a caseless comparison key.
 * Mirrors Python `(value or "").strip().casefold()` for tag dedupe / delete matching.
 *
 * JavaScript has no native casefold(); `toLocaleLowerCase('und')` uses the Unicode
 * default locale and matches Python casefold for typical CJK / Latin tag text.
 */
export function foldCase(value: string): string {
  return value.trim().toLocaleLowerCase('und')
}
