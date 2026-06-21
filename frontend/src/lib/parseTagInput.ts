/** 解析使用者輸入的標籤（支援半形/全形逗號、頓號、分號）。 */
export function parseTagInput(raw: string): string[] {
  return raw
    .split(/[,，、;；]/)
    .map((part) => part.trim())
    .filter(Boolean)
}
