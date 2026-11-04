// Instant front-view sketch of a procedural "blocky toy figure" from its look, drawn in SVG so the
// character editor reacts immediately; the Blender preview render is the accurate reference.

type Look = {
  body?: Record<string, number>;
  colors?: Record<string, string>;
  hair?: { style?: string };
  accessories?: { type: string; color?: string; lens?: string }[];
  clothing?: { top?: string; top_pattern?: string; bottom?: string };
  face?: { eye_size?: number; brow_thickness?: number; mouth_width?: number; freckles?: boolean };
};

const LONG_SLEEVES = new Set(["hoodie", "cardigan", "jacket", "sweater"]);

export function CharacterSVG({ look, width = 180, expression = "neutral" }: { look: Look; width?: number; expression?: string }) {
  const b = look.body || {};
  const c = look.colors || {};
  const col = (k: string, d: string) => c[k] || d;
  const height = Number(b.height ?? 1);
  const headS = Number(b.head_size ?? 1);
  const torsoW = Number(b.torso_width ?? 1);
  const limb = Number(b.limb_thickness ?? 1);
  const legL = Number(b.leg_length ?? 1);
  const armL = Number(b.arm_length ?? 1);
  const face = look.face || {};
  const clothing = look.clothing || {};
  const acc = new Map((look.accessories || []).map((a) => [a.type, a]));
  const hair = look.hair?.style || "short";

  // layout in a 200 x 320 box, feet on the ground line
  const ground = 305;
  const legH = 78 * legL * height;
  const torsoH = 72 * height;
  const headH = 64 * headS;
  const headW = 70 * headS;
  const torsoWpx = 74 * torsoW;
  const legW = 26 * limb;
  const armW = 18 * limb;
  const armH = 74 * armL * height;
  const cx = 100;
  const hipY = ground - legH;
  const shoulderY = hipY - torsoH;
  const headBottom = shoulderY - 6;
  const headTop = headBottom - headH;
  const eyeY = headTop + headH * 0.5;
  const eyeR = 6.5 * Number(face.eye_size ?? 1);
  const mouthW = 18 * Number(face.mouth_width ?? 1);
  const skin = col("skin", "#F2C39B");
  const top = col("top", "#3D6B8C");
  const accent = col("top_accent", "#F5D547");
  const bottom = col("bottom", "#2C3E50");
  const shoes = col("shoes", "#333333");
  const hairC = col("hair", "#3A2414");
  const eyes = col("eyes", "#1A1A1A");
  const lips = col("lips", "#A0524A");
  const sleeve = LONG_SLEEVES.has(clothing.top || "") ? top : skin;
  const pattern = clothing.top_pattern || "solid";
  const shorts = clothing.bottom === "shorts";
  const hat = acc.get("beanie") || acc.get("cap");
  const pid = `p${Math.abs(hash(JSON.stringify(look))) % 1e6}`;

  const mouth = (() => {
    const y = headTop + headH * 0.76;
    switch (expression) {
      case "happy":
        return <path d={`M${cx - mouthW / 2} ${y} Q${cx} ${y + 9} ${cx + mouthW / 2} ${y}`} stroke={lips} strokeWidth={3} fill="none" strokeLinecap="round" />;
      case "shocked":
        return <ellipse cx={cx} cy={y + 2} rx={mouthW / 4} ry={6} fill={lips} />;
      case "sad":
        return <path d={`M${cx - mouthW / 2} ${y + 5} Q${cx} ${y - 3} ${cx + mouthW / 2} ${y + 5}`} stroke={lips} strokeWidth={3} fill="none" strokeLinecap="round" />;
      default:
        return <path d={`M${cx - mouthW / 2} ${y} Q${cx} ${y + 4} ${cx + mouthW / 2} ${y}`} stroke={lips} strokeWidth={3} fill="none" strokeLinecap="round" />;
    }
  })();

  return (
    <svg viewBox="0 0 200 320" width={width} height={(width * 320) / 200} role="img" aria-label="character sketch">
      <defs>
        <pattern id={`${pid}-stripes`} width="12" height="12" patternUnits="userSpaceOnUse">
          <rect width="12" height="12" fill={top} />
          <rect width="12" height="5" fill={accent} />
        </pattern>
        <pattern id={`${pid}-dots`} width="12" height="12" patternUnits="userSpaceOnUse">
          <rect width="12" height="12" fill={top} />
          <circle cx="6" cy="6" r="2.4" fill={accent} />
        </pattern>
        <pattern id={`${pid}-plaid`} width="16" height="16" patternUnits="userSpaceOnUse">
          <rect width="16" height="16" fill={top} />
          <rect width="16" height="4" y="6" fill={accent} opacity="0.55" />
          <rect width="4" height="16" x="6" fill={accent} opacity="0.55" />
        </pattern>
        <linearGradient id={`${pid}-gradient`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={top} />
          <stop offset="1" stopColor={accent} />
        </linearGradient>
        <radialGradient id={`${pid}-shade`} cx="35%" cy="25%" r="80%">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.28" />
          <stop offset="1" stopColor="#000000" stopOpacity="0.12" />
        </radialGradient>
      </defs>
      <ellipse cx={cx} cy={ground + 4} rx={58} ry={7} fill="#000" opacity="0.15" />
      {/* backpack behind the body */}
      {acc.get("backpack") && <rect x={cx - torsoWpx / 2 - 8} y={shoulderY + 6} width={torsoWpx + 16} height={torsoH * 0.8} rx={10} fill={acc.get("backpack")!.color || "#7A4A2A"} />}
      {/* legs */}
      {[-1, 1].map((s) => (
        <g key={s}>
          <rect x={cx + s * (torsoWpx * 0.22) - legW / 2} y={hipY} width={legW} height={legH - 10} rx={5} fill={shorts ? skin : bottom} />
          {shorts && <rect x={cx + s * (torsoWpx * 0.22) - legW / 2 - 1} y={hipY} width={legW + 2} height={legH * 0.38} rx={5} fill={bottom} />}
          <rect x={cx + s * (torsoWpx * 0.22) - legW / 2 - 3} y={ground - 14} width={legW + 6} height={14} rx={5} fill={shoes} />
        </g>
      ))}
      {/* arms */}
      {[-1, 1].map((s) => (
        <g key={s}>
          <rect x={cx + s * (torsoWpx / 2 + armW / 2 + 1) - armW / 2} y={shoulderY + 4} width={armW} height={armH - 14} rx={7} fill={sleeve} />
          <rect x={cx + s * (torsoWpx / 2 + armW / 2 + 1) - armW / 2} y={shoulderY + armH - 18} width={armW} height={16} rx={7} fill={skin} />
        </g>
      ))}
      {/* torso */}
      <rect x={cx - torsoWpx / 2} y={shoulderY} width={torsoWpx} height={torsoH} rx={10}
        fill={pattern === "solid" || pattern === "emblem" ? top : `url(#${pid}-${pattern})`} />
      {pattern === "emblem" && <circle cx={cx} cy={shoulderY + torsoH * 0.42} r={9} fill={accent} />}
      {clothing.top === "hoodie" && <path d={`M${cx - 16} ${shoulderY + 2} L${cx} ${shoulderY + 16} L${cx + 16} ${shoulderY + 2}`} stroke={accent} strokeWidth={3} fill="none" />}
      {(clothing.top === "cardigan" || clothing.top === "jacket") && <rect x={cx - 4} y={shoulderY} width={8} height={torsoH} fill={accent} />}
      {acc.get("backpack") && [-1, 1].map((s) => <rect key={s} x={cx + s * torsoWpx * 0.28 - 3} y={shoulderY} width={6} height={torsoH * 0.6} fill="#5A3A20" />)}
      <rect x={cx - torsoWpx / 2} y={shoulderY} width={torsoWpx} height={torsoH} rx={10} fill={`url(#${pid}-shade)`} />
      {acc.get("bowtie") && <path d={`M${cx - 12} ${shoulderY + 4} L${cx} ${shoulderY + 10} L${cx - 12} ${shoulderY + 16} Z M${cx + 12} ${shoulderY + 4} L${cx} ${shoulderY + 10} L${cx + 12} ${shoulderY + 16} Z`} fill={acc.get("bowtie")!.color || "#C0392B"} />}
      {/* neck + head */}
      <rect x={cx - 9} y={headBottom - 4} width={18} height={12} fill={skin} />
      {(hair === "long" || hair === "bob") && !hat && <rect x={cx - headW / 2 - 5} y={headTop - 4} width={headW + 10} height={hair === "long" ? headH * 1.25 : headH * 0.9} rx={12} fill={hairC} />}
      {hair === "ponytail" && <rect x={cx + headW / 2 - 6} y={headTop + 8} width={14} height={headH * 0.9} rx={7} fill={hairC} />}
      <rect x={cx - headW / 2} y={headTop} width={headW} height={headH} rx={14} fill={skin} />
      <rect x={cx - headW / 2} y={headTop} width={headW} height={headH} rx={14} fill={`url(#${pid}-shade)`} />
      {/* hair on top */}
      {!hat && hair === "spiky" && (
        <path d={`M${cx - headW / 2} ${headTop + 12} L${cx - headW / 3} ${headTop - 14} L${cx - headW / 8} ${headTop + 2} L${cx + headW / 12} ${headTop - 18} L${cx + headW / 4} ${headTop + 2} L${cx + headW / 2.2} ${headTop - 12} L${cx + headW / 2} ${headTop + 12} Z`} fill={hairC} />
      )}
      {!hat && ["short", "ponytail", "bun", "bob", "long"].includes(hair) && <rect x={cx - headW / 2 - 2} y={headTop - 6} width={headW + 4} height={18} rx={9} fill={hairC} />}
      {!hat && hair === "bun" && <circle cx={cx} cy={headTop - 12} r={12} fill={hairC} />}
      {!hat && hair === "curly" && [0, 1, 2, 3, 4].map((i) => <circle key={i} cx={cx - headW / 2 + 6 + i * (headW - 12) / 4} cy={headTop - 2} r={11} fill={hairC} />)}
      {hat && (acc.get("beanie") ? (
        <path d={`M${cx - headW / 2 - 3} ${headTop + 14} Q${cx} ${headTop - 34} ${cx + headW / 2 + 3} ${headTop + 14} Z`} fill={hat.color || "#4E7A5A"} />
      ) : (
        <g>
          <path d={`M${cx - headW / 2 - 2} ${headTop + 10} Q${cx} ${headTop - 26} ${cx + headW / 2 + 2} ${headTop + 10} Z`} fill={hat.color || "#C0392B"} />
          <rect x={cx - 6} y={headTop + 4} width={headW / 2 + 16} height={7} rx={3} fill={hat.color || "#C0392B"} />
        </g>
      ))}
      {/* face */}
      {[-1, 1].map((s) => (
        <g key={s}>
          <ellipse cx={cx + s * headW * 0.2} cy={eyeY} rx={eyeR} ry={eyeR * (expression === "shocked" ? 1.35 : 1.15)} fill="#fff" />
          <circle cx={cx + s * headW * 0.2} cy={eyeY + 1} r={eyeR * 0.55} fill={eyes} />
          <rect x={cx + s * headW * 0.2 - 8} y={eyeY - eyeR - 8 - (expression === "shocked" ? 4 : 0)} width={16} height={3 * Number(face.brow_thickness ?? 1)} rx={1.5} fill={hairC}
            transform={expression === "sad" ? `rotate(${s * -10} ${cx + s * headW * 0.2} ${eyeY - eyeR - 7})` : undefined} />
        </g>
      ))}
      {face.freckles && [-1, 1].map((s) => [0, 1, 2].map((i) => <circle key={`${s}${i}`} cx={cx + s * (headW * 0.2 + (i - 1) * 4)} cy={eyeY + eyeR + 6 + (i % 2) * 2} r={1.2} fill="#9B5B3A" opacity="0.7" />))}
      {mouth}
      {(acc.get("glasses") || acc.get("goggles")) && [-1, 1].map((s) => (
        <rect key={s} x={cx + s * headW * 0.2 - eyeR - 3} y={eyeY - eyeR - 3} width={2 * eyeR + 6} height={2 * eyeR + 6} rx={acc.get("goggles") ? 7 : 3}
          fill={acc.get("goggles") ? (acc.get("goggles")!.lens || "#7FD3E8") : "none"} fillOpacity={0.35}
          stroke={(acc.get("goggles") || acc.get("glasses"))!.color || "#333"} strokeWidth={3} />
      ))}
      {acc.get("headphones") && (
        <g fill="none" stroke={acc.get("headphones")!.color || "#222"} strokeWidth={5}>
          <path d={`M${cx - headW / 2 - 2} ${eyeY} Q${cx} ${headTop - 30} ${cx + headW / 2 + 2} ${eyeY}`} />
          <rect x={cx - headW / 2 - 9} y={eyeY - 8} width={9} height={18} rx={3} fill={acc.get("headphones")!.color || "#222"} />
          <rect x={cx + headW / 2} y={eyeY - 8} width={9} height={18} rx={3} fill={acc.get("headphones")!.color || "#222"} />
        </g>
      )}
    </svg>
  );
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}
