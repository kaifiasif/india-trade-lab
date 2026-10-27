import { useEffect, useRef } from "react";
import gsap from "gsap";

const COLORS = ["#7760ce", "#358977", "#e2b84a", "#d0679a", "#4f7fd8"];

/** A short burst of paper confetti when `fire` changes. Purely decorative. */
export function Confetti({ fire }: { fire: number }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!fire || !box.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const host = box.current;
    const pieces: HTMLSpanElement[] = [];
    for (let i = 0; i < 28; i++) {
      const piece = document.createElement("span");
      piece.className = "absolute left-1/2 top-1/2 block h-2.5 w-1.5 rounded-[1px]";
      piece.style.background = COLORS[i % COLORS.length];
      host.appendChild(piece);
      pieces.push(piece);
    }
    const tl = gsap.timeline({ onComplete: () => pieces.forEach((piece) => piece.remove()) });
    pieces.forEach((piece) => {
      const angle = Math.random() * Math.PI * 2;
      const distance = 70 + Math.random() * 110;
      tl.fromTo(
        piece,
        { x: 0, y: 0, rotation: 0, opacity: 1 },
        {
          x: Math.cos(angle) * distance,
          y: Math.sin(angle) * distance + 60,
          rotation: Math.random() * 540 - 270,
          opacity: 0,
          duration: 1.2 + Math.random() * 0.5,
          ease: "power2.out",
        },
        0,
      );
    });
    return () => {
      tl.kill();
      pieces.forEach((piece) => piece.remove());
    };
  }, [fire]);
  return <div ref={box} aria-hidden className="pointer-events-none absolute inset-0 overflow-visible" />;
}
