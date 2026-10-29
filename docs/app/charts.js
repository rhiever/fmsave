// SVG drawings: the 52-wedge percentile wheel and the position pitch. Colours come from the
// theme's CSS classes and variables, so both follow light and dark mode.

import { ATTRIBUTES, GROUP_HUE, POSITION_SLOTS, esc, ordinal } from "./catalog.js";

export const WHEEL_ORDER = Object.entries(ATTRIBUTES).flatMap(([group, list]) => list.map(([name, , label]) => [group, "attributes_" + name, label]));

// rankOf(key) gives a percentile from 0 to 99, or null when the player has none.
export function wheel(size, rankOf, [big, small]) {
  const c = size / 2, R = size / 2 - 2, r0 = size * 0.14, step = (2 * Math.PI) / WHEEL_ORDER.length;
  const pt = (a, r) => `${(c + r * Math.cos(a)).toFixed(1)},${(c + r * Math.sin(a)).toFixed(1)}`;
  const wedge = (a0, a1, r) => `M${pt(a0, r0)}L${pt(a0, r)}A${r},${r} 0 0 1 ${pt(a1, r)}L${pt(a1, r0)}Z`;
  const paths = WHEEL_ORDER.map(([group, key, label], k) => {
    const p = rankOf(key);
    const a0 = k * step - Math.PI / 2 + 0.012, a1 = (k + 1) * step - Math.PI / 2 - 0.012;
    const track = `<path class="w-track" d="${wedge(a0, a1, R)}"/>`;
    if (p === null || p === undefined) return track;
    const r = r0 + (R - r0) * (Math.max(p, 2) / 100);
    return `${track}<path d="${wedge(a0, a1, r)}" style="fill:rgb(var(--${GROUP_HUE[group]}))"><title>${esc(label)}: ${ordinal(p)} percentile</title></path>`;
  });
  return `${paths.join("")}<circle class="w-hole" cx="${c}" cy="${c}" r="${r0 - 2}"/>` +
    `<text class="w-big" x="${c}" y="${c - size * 0.012}" text-anchor="middle" font-size="${Math.max(15, size * 0.075)}">${esc(big)}</text>` +
    `<text class="w-small" x="${c}" y="${c + size * 0.06}" text-anchor="middle" font-size="${Math.max(11, size * 0.045)}">${esc(small)}</text>`;
}

const PITCH_SPOTS = { stc: [50, 12], aml: [16, 34], amc: [50, 34], amr: [84, 34], ml: [16, 56], mc: [50, 56], mr: [84, 56], wbl: [16, 78], dm: [50, 78], wbr: [84, 78], dl: [16, 100], dc: [50, 100], dr: [84, 100], sw: [50, 120], gk: [50, 140] };

// ratingOf(slot) gives the player's 1 to 20 rating there.
export function pitch(ratingOf) {
  const W = 100, H = 152;
  const marks = POSITION_SLOTS.map(([slot, label]) => {
    const [x, y] = PITCH_SPOTS[slot];
    const v = ratingOf(slot);
    const band = v >= 18 ? "top" : v >= 15 ? "good" : v >= 10 ? "ok" : "low";
    return `<g><title>${esc(label)}: ${v}</title><circle class="p-${band}" cx="${x}" cy="${y}" r="6.6"/>` +
      `<text class="p-num ${band}" x="${x}" y="${y + 2.4}" text-anchor="middle" font-size="6.6">${v}</text>` +
      `<text class="p-label" x="${x}" y="${y + 11.8}" text-anchor="middle" font-size="3.9">${esc(label)}</text></g>`;
  });
  return `<svg class="pitch" viewBox="-4 -4 ${W + 8} ${H + 8}" role="img" aria-label="Position ratings on a pitch">` +
    `<rect class="p-field" width="${W}" height="${H}" rx="3"/><line class="p-line" x1="0" y1="${H / 2}" x2="${W}" y2="${H / 2}"/>` +
    `<circle class="p-line" cx="50" cy="${H / 2}" r="9"/><rect class="p-line" x="22" y="${H - 22}" width="56" height="22"/>` +
    `<rect class="p-line" x="22" width="56" height="22"/>${marks.join("")}</svg>`;
}
