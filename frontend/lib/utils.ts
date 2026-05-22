import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * 合并 Tailwind CSS 类名，解决样式冲突
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * 截断字符串
 */
export function truncate(str: string, length: number = 8) {
  if (!str) return "-";
  return str.length > length ? str.slice(0, length) : str;
}
