import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function rupees(value: unknown, precise = false): string {
  const number = typeof value === "string" ? Number(value) : (value as number);
  if (value === null || value === undefined || value === "" || Number.isNaN(number)) return "—";
  return (precise ? inr2 : inr).format(number);
}

export function signed(value: unknown): string {
  const number = Number(value);
  if (value === null || value === undefined || Number.isNaN(number)) return "—";
  return (number > 0 ? "+" : "") + inr2.format(number);
}

export function time(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });
}

export function dateTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
  });
}

export function readable(value?: string | null): string {
  return String(value ?? "").replaceAll("_", " ").replaceAll("-", " ");
}
