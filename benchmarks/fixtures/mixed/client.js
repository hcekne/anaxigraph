import { formatName } from "./format";

export function greeting(name) {
  return `Hello, ${formatName(name)}`;
}
