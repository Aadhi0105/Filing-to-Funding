import type { ButtonHTMLAttributes } from "react";
import { Slot } from "@radix-ui/react-slot";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  asChild?: boolean;
  variant?: "primary" | "outline";
};

// Project-local shadcn-style Button primitive.
export function Button({ asChild, variant = "outline", className, ...props }: Props) {
  const Element = asChild ? Slot : "button";
  return <Element className={twMerge(clsx("button", `button-${variant}`, className))} {...props} />;
}
