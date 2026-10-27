import { useEffect, useId, useLayoutEffect, useRef } from "react";
import gsap from "gsap";
import { MASCOTS, type MascotKey } from "./data";

export type Mood = "idle" | "thinking" | "happy" | "alert" | "sleep" | "wave";

interface Props {
  kind: MascotKey;
  mood?: Mood;
  size?: number;
  /** Walk on from the side, or pop up, the first time it mounts. */
  entrance?: "walk" | "pop" | "none";
  /** Replay a reaction whenever this value changes (a new pick, a target hit, a stop). */
  react?: string | number | null;
  className?: string;
  title?: string;
  onClick?: () => void;
  /** Seconds to wait before the entrance, for staggered groups. */
  delay?: number;
}

const reduced = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * One member of the robot family, drawn in SVG and moved with GSAP.
 * Purposeful motion: breathing, blinking and a mood that follows real events
 * (thinking while agents run, a nod on a pick, a flinch on a stop, asleep when
 * the desk sits out). Expressive motion: walk-ons, hops and waves on click.
 * With reduced motion, every mascot holds its final pose.
 */
export function Mascot({ kind, mood = "idle", size = 96, entrance = "none", react, className, title, onClick, delay = 0 }: Props) {
  const spec = MASCOTS[kind];
  const id = useId().replace(/:/g, "");
  const root = useRef<SVGSVGElement>(null);
  const actor = useRef<SVGGElement>(null);
  const head = useRef<SVGGElement>(null);
  const eyes = useRef<SVGGElement>(null);
  const antenna = useRef<SVGGElement>(null);
  const shadow = useRef<SVGEllipseElement>(null);
  const zzz = useRef<SVGGElement>(null);
  const dots = useRef<SVGGElement>(null);
  const sparkle = useRef<SVGGElement>(null);
  const mounted = useRef(false);

  // Entrance, once.
  useLayoutEffect(() => {
    if (reduced() || entrance === "none" || !actor.current) return;
    const ctx = gsap.context(() => {
      if (entrance === "walk") {
        gsap
          .timeline({ delay })
          .from(actor.current, { x: -160, duration: 1.1, ease: "power2.out" })
          .from(actor.current, { y: -10, duration: 0.18, repeat: 5, yoyo: true, ease: "sine.inOut" }, 0)
          .to(actor.current, { rotation: 0, duration: 0.2 });
      } else {
        gsap.from(actor.current, { y: 30, scale: 0.6, opacity: 0, duration: 0.6, delay, ease: "back.out(2)", transformOrigin: "50% 100%" });
      }
    }, root);
    return () => ctx.revert();
  }, [entrance]);

  // Mood loops: breathing and blinking always; the rest by mood.
  useEffect(() => {
    if (!actor.current) return;
    const motion = !reduced();
    const ctx = gsap.context(() => {
      gsap.set([zzz.current, dots.current, sparkle.current], { autoAlpha: 0 });
      gsap.set(eyes.current, { scaleY: mood === "sleep" ? 0.12 : 1, transformOrigin: "50% 50%" });
      if (!motion) {
        if (mood === "sleep") gsap.set(zzz.current, { autoAlpha: 1 });
        if (mood === "thinking") gsap.set(dots.current, { autoAlpha: 1 });
        return;
      }
      gsap.to(head.current, { y: -2.5, duration: 1.8, repeat: -1, yoyo: true, ease: "sine.inOut" });
      gsap.to(shadow.current, { scaleX: 0.94, duration: 1.8, repeat: -1, yoyo: true, ease: "sine.inOut", transformOrigin: "50% 50%" });
      if (antenna.current) {
        gsap.to(antenna.current, { rotation: 6, duration: 1.2, repeat: -1, yoyo: true, ease: "sine.inOut", transformOrigin: "126px 64px" });
      }
      if (mood !== "sleep") {
        const blink = gsap.timeline({ repeat: -1, repeatDelay: 2.6 + Math.random() * 2.2 });
        blink.to(eyes.current, { scaleY: 0.1, duration: 0.07, transformOrigin: "50% 50%" }).to(eyes.current, { scaleY: 1, duration: 0.11 });
      }
      if (mood === "thinking") {
        gsap.to(eyes.current, { x: 6, duration: 0.9, repeat: -1, yoyo: true, ease: "sine.inOut", repeatDelay: 0.6 });
        gsap.set(dots.current, { autoAlpha: 1 });
        gsap.fromTo(
          dots.current?.children ?? [],
          { y: 0, opacity: 0.25 },
          { y: -5, opacity: 1, duration: 0.45, stagger: 0.15, repeat: -1, yoyo: true, ease: "sine.inOut" },
        );
      }
      if (mood === "sleep") {
        gsap.set(zzz.current, { autoAlpha: 1 });
        gsap.fromTo(
          zzz.current?.children ?? [],
          { y: 8, opacity: 0 },
          { y: -14, opacity: 1, duration: 1.8, stagger: 0.6, repeat: -1, ease: "sine.out" },
        );
        gsap.to(head.current, { rotation: -4, duration: 2.4, repeat: -1, yoyo: true, ease: "sine.inOut", transformOrigin: "126px 179px" });
      }
      if (mood === "alert") {
        gsap.fromTo(actor.current, { x: -3 }, { x: 3, duration: 0.07, repeat: 7, yoyo: true, ease: "none", clearProps: "x" });
      }
      if (mood === "happy" || mood === "wave") {
        hop();
      }
    }, root);
    return () => ctx.revert();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mood]);

  // Event reactions.
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    if (react === null || react === undefined || reduced()) return;
    hop();
  }, [react]);

  function hop() {
    if (!actor.current || reduced()) return;
    const tl = gsap.timeline();
    tl.to(actor.current, { y: -18, duration: 0.22, ease: "power2.out" })
      .to(actor.current, { y: 0, duration: 0.35, ease: "bounce.out" })
      .to(shadow.current, { scaleX: 0.7, duration: 0.22, transformOrigin: "50% 50%" }, 0)
      .to(shadow.current, { scaleX: 1, duration: 0.35 }, 0.22);
    gsap.set(sparkle.current, { autoAlpha: 1 });
    tl.fromTo(
      sparkle.current?.children ?? [],
      { scale: 0, transformOrigin: "50% 50%" },
      { scale: 1, duration: 0.3, stagger: 0.06, ease: "back.out(3)" },
      0.05,
    ).to(sparkle.current, { autoAlpha: 0, duration: 0.4 }, 0.8);
  }

  const p = `m${id}`;
  return (
    <svg
      ref={root}
      viewBox="0 0 250 250"
      width={size}
      height={size}
      role="img"
      aria-label={title ?? `${spec.name}, ${spec.role}`}
      className={className}
      onClick={() => {
        hop();
        onClick?.();
      }}
      style={{ cursor: onClick ? "pointer" : undefined, overflow: "visible" }}
    >
      <defs>
        <linearGradient id={`${p}-body`} x1="70" y1="65" x2="180" y2="218" gradientUnits="userSpaceOnUse">
          <stop stopColor="#fff" />
          <stop offset="1" stopColor="#d9d8ee" />
        </linearGradient>
        <linearGradient id={`${p}-face`} x1="76" y1="86" x2="167" y2="156" gradientUnits="userSpaceOnUse">
          <stop stopColor="#302d4b" />
          <stop offset="1" stopColor="#141326" />
        </linearGradient>
        <linearGradient id={`${p}-ear`} x1="45" y1="95" x2="75" y2="141" gradientUnits="userSpaceOnUse">
          <stop stopColor="#fff" />
          <stop offset="1" stopColor={spec.accent} />
        </linearGradient>
      </defs>
      <ellipse ref={shadow} cx="129" cy="228" rx="55" ry="9" fill={spec.accent} opacity=".18" />
      <g ref={actor}>
        {spec.antenna && (
          <g ref={antenna}>
            <path d="M126 64V40" stroke="#dedcf5" strokeWidth="7" strokeLinecap="round" />
            <circle cx="126" cy="35" r="9" fill={spec.accent} />
            <circle cx="123" cy="32" r="3" fill="#fff" opacity=".7" />
          </g>
        )}
        <g dangerouslySetInnerHTML={{ __html: spec.behind }} />
        <path
          d="M96 166H157L169 201C173 216 161 225 151 220L126 209 102 220C90 225 79 215 84 201L96 166Z"
          fill={`url(#${p}-body)`}
        />
        <path d="M96 176L80 188" stroke="#e7e6f7" strokeWidth="17" strokeLinecap="round" />
        <path d="M157 175L178 161" stroke="#e7e6f7" strokeWidth="17" strokeLinecap="round" />
        <g ref={head}>
          <rect x="46" y="99" width="26" height="43" rx="13" fill={`url(#${p}-ear)`} />
          <rect x="180" y="98" width="22" height="43" rx="11" fill={`url(#${p}-ear)`} />
          <rect x="62" y="61" width="124" height="118" rx="39" fill={`url(#${p}-body)`} />
          <rect x="75" y="80" width="99" height="77" rx="28" fill={`url(#${p}-face)`} />
          <g ref={eyes}>
            <rect x="92" y="107" width="14" height="23" rx="7" fill={spec.eye} />
            <rect x="143" y="107" width="14" height="23" rx="7" fill={spec.eye} />
          </g>
          <path d="M119 136C123 140 129 140 133 136" stroke={spec.eye} strokeWidth="3" strokeLinecap="round" />
          <circle cx="86" cy="140" r="5" fill={spec.accent} opacity=".45" />
          <circle cx="163" cy="140" r="5" fill={spec.accent} opacity=".45" />
        </g>
        <g dangerouslySetInnerHTML={{ __html: spec.front }} />
        <g ref={dots} fill={spec.accent}>
          <circle cx="190" cy="52" r="5" />
          <circle cx="206" cy="40" r="6" />
          <circle cx="224" cy="26" r="7" />
        </g>
        <g ref={zzz} fill={spec.accent} fontFamily="Inter Variable, sans-serif" fontWeight="800">
          <text x="190" y="60" fontSize="18">z</text>
          <text x="204" y="44" fontSize="22">z</text>
          <text x="220" y="26" fontSize="26">Z</text>
        </g>
        <g ref={sparkle} fill={spec.accent}>
          <path d="M40 60l4 10 10 4-10 4-4 10-4-10-10-4 10-4z" />
          <path d="M212 70l3 7 7 3-7 3-3 7-3-7-7-3 7-3z" />
          <path d="M200 20l2.5 6 6 2.5-6 2.5-2.5 6-2.5-6-6-2.5 6-2.5z" />
        </g>
      </g>
    </svg>
  );
}
