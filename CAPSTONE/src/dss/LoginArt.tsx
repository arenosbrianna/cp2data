import React from 'react';

// Flat illustrations (layered shapes for depth, no gradients) of maki, nigiri, ramen and rice bowls for the sign-in background. Decorative only.
const NORI = '#1B2540', NORI_HI = '#34436B', RICE = '#FFFFFF', RICE_EDGE = '#DCE2EE', RICE_SHADE = '#EEF1F8';
const SALMON = '#FF8A3D', SALMON_DK = '#EE6A2A', SALMON_LT = '#FFD9B8';
const GREEN = '#6FAE2B', GREEN_LT = '#A9D863', NAVY = '#1E3A8A', NAVY_DK = '#152B6B', NAVY_LT = '#3552B8';
const RED = '#B91C1C', RED_DK = '#8F1414', RED_FOOT = '#6F1010';

const grains = (pts: [number, number, number][]) => pts.map(([x, y, r], i) => <ellipse key={i} cx={x} cy={y} rx={3.2} ry={1.8} transform={`rotate(${r} ${x} ${y})`} fill={RICE_SHADE} stroke={RICE_EDGE} strokeWidth=".8" />);

const Defs: React.FC = () => (
  <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true" focusable="false">
    <defs>
      {/* maki: one cut piece standing (rice face up) and one lying on its side */}
      <symbol id="art-maki" viewBox="0 0 150 112">
        {/* standing piece */}
        <path d="M12 38v40c0 11 14 19 33 19s33-8 33-19V38z" fill={NORI} />
        <path d="M20 44v34c0 6 8 11 18 13" stroke={NORI_HI} strokeWidth="2.6" strokeLinecap="round" fill="none" />
        <path d="M66 46v32c0 6-6 10-14 12" stroke="#0F1730" strokeWidth="3" strokeLinecap="round" fill="none" opacity=".6" />
        <ellipse cx="45" cy="38" rx="33" ry="17" fill={NORI} />
        <ellipse cx="45" cy="38" rx="28" ry="13.5" fill={RICE} stroke={RICE_EDGE} strokeWidth="1.6" />
        {grains([[24, 36, 10], [34, 46, -10], [58, 47, 12], [68, 38, -8], [58, 29, 10], [32, 29, -12]])}
        <ellipse cx="40" cy="38" rx="11" ry="6.5" fill={SALMON} />
        <path d="M32 36c4-3 9-3 13-1M36 41c4 1 8 0 11-2" stroke={SALMON_LT} strokeWidth="1.8" strokeLinecap="round" fill="none" />
        <ellipse cx="58" cy="40" rx="6" ry="4" fill={GREEN} /><ellipse cx="58" cy="40" rx="3.4" ry="2.2" fill={GREEN_LT} />
        {/* lying piece */}
        <path d="M92 66h40v34H92z" fill={NORI} />
        <path d="M96 72h32" stroke={NORI_HI} strokeWidth="2.6" strokeLinecap="round" />
        <ellipse cx="132" cy="83" rx="9" ry="17" fill="#0F1730" />
        <ellipse cx="92" cy="83" rx="9" ry="17" fill={NORI} />
        <ellipse cx="92" cy="83" rx="6.5" ry="14" fill={RICE} stroke={RICE_EDGE} strokeWidth="1.4" />
        <ellipse cx="91" cy="80" rx="3.6" ry="6.5" fill={SALMON} />
        <ellipse cx="93" cy="90" rx="2.6" ry="4.2" fill={GREEN} />
      </symbol>

      {/* nigiri: marbled salmon draped over a rice block, with a nori band */}
      <symbol id="art-nigiri" viewBox="0 0 160 92">
        <path d="M20 50C20 42 44 38 80 38s60 4 60 12v20c0 8-16 12-60 12S20 78 20 70z" fill={RICE} stroke={RICE_EDGE} strokeWidth="2" />
        <path d="M22 72c8 7 30 10 58 10s50-3 58-10c-2 10-20 14-58 14S24 82 22 72z" fill={RICE_SHADE} />
        {grains([[42, 56, 15], [60, 60, -30], [84, 58, 20], [108, 60, -10], [126, 56, 35], [50, 72, 40], [76, 74, -20], [100, 73, 25], [120, 70, -35]])}
        <path d="M8 52C14 24 48 14 80 14s66 10 72 38c-22 10-46 13-72 13S30 62 8 52z" fill={SALMON_DK} />
        <path d="M10 48C16 24 50 16 80 16s62 8 68 32c-22 8-44 11-68 11S32 56 10 48z" fill={SALMON} />
        <path d="M24 38c20-12 44-16 68-13M40 48c24-8 50-10 78-5M60 30c16-5 34-6 52-2" stroke={SALMON_LT} strokeWidth="4.2" strokeLinecap="round" fill="none" />
        <path d="M22 30c14-10 34-14 52-14" stroke="#FFFFFF" strokeOpacity=".6" strokeWidth="3" strokeLinecap="round" fill="none" />
        <rect x="68" y="8" width="24" height="80" rx="3" fill={NORI} />
        <path d="M73 14v68" stroke={NORI_HI} strokeWidth="2.4" strokeLinecap="round" />
      </symbol>

      {/* ramen: red bowl with curved trim, broth, noodles, chashu, soft-boiled egg, narutomaki, nori and scallions */}
      <symbol id="art-ramen" viewBox="0 0 160 134">
        <defs><clipPath id="ramen-body-clip"><path d="M6 58c0 38 32 62 74 62s74-24 74-62z" /></clipPath></defs>
        <g fill="none" stroke="#C3CCDD" strokeWidth="3.2" strokeLinecap="round" opacity=".85"><path d="M50 22c-8-7 8-12 0-22" /><path d="M72 20c-8-7 8-12 0-20" /><path d="M94 24c-7-6 7-10 0-18" /></g>
        <g transform="translate(0 12)">
          {/* foot first, so the bowl covers its top edge */}
          <path d="M56 108h48l5 16H51z" fill={RED_FOOT} />
          {/* bowl body, with shading and trim clipped to its outline */}
          <path d="M6 58c0 38 32 62 74 62s74-24 74-62z" fill={RED} />
          <g clipPath="url(#ramen-body-clip)">
            <path d="M118 58c-2 28-16 52-44 62h84V58z" fill={RED_DK} opacity=".7" />
            <path d="M-4 78Q80 108 164 78" stroke="#FFFFFF" strokeWidth="3.6" fill="none" />
            <path d="M-4 92Q80 122 164 92" stroke="#FFFFFF" strokeOpacity=".65" strokeWidth="2.4" fill="none" />
            <path d="M16 84c8 14 22 22 38 26" stroke="#FFFFFF" strokeOpacity=".22" strokeWidth="3" strokeLinecap="round" fill="none" />
          </g>
          {/* rim and broth */}
          <ellipse cx="80" cy="58" rx="74" ry="24" fill="#FFFFFF" stroke={RICE_EDGE} strokeWidth="2" />
          <ellipse cx="80" cy="58" rx="66" ry="19" fill="#E2A24E" />
          <ellipse cx="80" cy="60" rx="58" ry="14" fill="#D68F3A" opacity=".55" />
          {/* nori standing at the back */}
          <path d="M84 20l18 3-4 34-18-3z" fill={NORI} /><path d="M88 26l11 2" stroke={NORI_HI} strokeWidth="2" strokeLinecap="round" />
          {/* noodles */}
          <g fill="none" stroke="#F7DB82" strokeWidth="4.2" strokeLinecap="round">
            <path d="M32 58c9-5 16 5 25 0s17 5 26 0 17 5 26 0 12 3 16 0" /><path d="M38 66c9-5 16 5 25 0s17 5 26 0 17 5 24 0" /><path d="M46 52c8-4 14 4 22 0s14 4 22 0 12 3 18 0" />
          </g>
          <g stroke="#E8C75C" strokeWidth="1.4" strokeLinecap="round" fill="none"><path d="M36 60c9-4 16 4 25 0M62 68c9-4 16 4 25 0" /></g>
          {/* chashu */}
          <ellipse cx="50" cy="52" rx="19" ry="9.5" fill="#9A5A32" /><ellipse cx="50" cy="51" rx="18" ry="8.6" fill="#C98558" />
          <path d="M38 50c6-4 14-4 22-1M42 55c6 2 14 1 20-2" stroke="#EBC09A" strokeWidth="2" strokeLinecap="round" fill="none" />
          <ellipse cx="72" cy="45" rx="17" ry="8.4" fill="#9A5A32" /><ellipse cx="72" cy="44" rx="16" ry="7.6" fill="#D49467" />
          <path d="M62 43c6-3 12-3 18-1" stroke="#EBC09A" strokeWidth="2" strokeLinecap="round" fill="none" />
          {/* soft-boiled egg */}
          <ellipse cx="104" cy="52" rx="13" ry="9" fill="#FFFFFF" stroke={RICE_EDGE} strokeWidth="1.4" />
          <ellipse cx="104" cy="52" rx="7.4" ry="5.2" fill="#F59E0B" /><ellipse cx="102" cy="50" rx="2.6" ry="1.6" fill="#FCD34D" />
          {/* narutomaki */}
          <circle cx="126" cy="62" r="9" fill="#FFFFFF" stroke={RICE_EDGE} strokeWidth="1.4" />
          <path d="M126 62m-2 0a2 2 0 1 1 4 0a5 5 0 1 1-8 0a8 8 0 1 1 12 0" stroke="#F472B6" strokeWidth="1.8" strokeLinecap="round" fill="none" />
          {/* scallions */}
          <g fill={GREEN}><ellipse cx="88" cy="63" rx="3.4" ry="1.8" /><ellipse cx="94" cy="67" rx="3.4" ry="1.8" transform="rotate(30 94 67)" /><ellipse cx="62" cy="65" rx="3.4" ry="1.8" transform="rotate(-20 62 65)" /><ellipse cx="112" cy="66" rx="3.4" ry="1.8" /><ellipse cx="38" cy="63" rx="3.4" ry="1.8" transform="rotate(20 38 63)" /></g>
          <g fill={GREEN_LT}><circle cx="88" cy="63" r="1" /><circle cx="62" cy="65" r="1" /><circle cx="112" cy="66" r="1" /></g>
          {/* chopsticks resting on the rim, clear of the toppings */}
          <path d="M142 4L106 42M150 14L114 50" stroke="#B88A4A" strokeWidth="5.4" strokeLinecap="round" />
          <path d="M142 4L106 42M150 14L114 50" stroke="#E8C185" strokeWidth="3.6" strokeLinecap="round" />
        </g>
      </symbol>

      {/* rice bowl with chopsticks */}
      <symbol id="art-bowl" viewBox="0 0 150 146">
        <g fill="none" stroke="#C3CCDD" strokeWidth="3.2" strokeLinecap="round" opacity=".8"><path d="M58 22c-8-7 8-12 0-22" /><path d="M78 20c-8-7 8-12 0-20" /><path d="M96 24c-7-6 7-10 0-18" /></g>
        <g transform="translate(0 12)">
          <path d="M24 66C24 36 48 18 75 18s51 18 51 48z" fill={RICE} stroke={RICE_EDGE} strokeWidth="2" />
          <path d="M100 30c14 10 24 22 26 36H92c8-10 10-24 8-36z" fill={RICE_SHADE} />
          {grains([[54, 44, 20], [74, 34, -25], [96, 42, 30], [62, 56, -35], [84, 54, 10], [44, 60, 45], [108, 56, -20], [70, 46, 40]])}
          <path d="M104 4L68 52M118 10L76 58" stroke="#B88A4A" strokeWidth="6" strokeLinecap="round" />
          <path d="M104 4L68 52M118 10L76 58" stroke="#E8C185" strokeWidth="4" strokeLinecap="round" />
          <path d="M6 60h138c0 38-30 62-69 62S6 98 6 60z" fill={NAVY} />
          <path d="M6 60h138v9H6z" fill={NAVY_LT} />
          <path d="M120 74c-4 22-22 40-48 44 40 2 66-20 72-58z" fill={NAVY_DK} opacity=".7" />
          <g fill="none" stroke="#FFFFFF" strokeOpacity=".45" strokeWidth="2">
            <path d="M22 88a10 10 0 0 1 20 0M42 88a10 10 0 0 1 20 0M62 88a10 10 0 0 1 20 0M82 88a10 10 0 0 1 20 0M102 88a10 10 0 0 1 20 0" />
            <path d="M32 100a10 10 0 0 1 20 0M52 100a10 10 0 0 1 20 0M72 100a10 10 0 0 1 20 0M92 100a10 10 0 0 1 20 0" />
          </g>
          <path d="M50 114h50v16c0 2-2 4-4 4H54c-2 0-4-2-4-4z" fill={NAVY_DK} />
          <path d="M14 66c10 22 24 34 40 40" stroke="#FFFFFF" strokeOpacity=".3" strokeWidth="3" strokeLinecap="round" fill="none" />
        </g>
      </symbol>
    </defs>
  </svg>
);


const VB: Record<string, [number, number]> = { 'art-maki': [150, 112], 'art-nigiri': [160, 92], 'art-ramen': [160, 134], 'art-bowl': [150, 146] };

interface Piece { id: string; w: number; style: React.CSSProperties; m?: boolean }
// Placed around the edges, clear of the sign-in card and logo in the middle. `m` marks the pieces kept on phones.
const pieces: Piece[] = [
  { id: 'art-maki', w: 180, style: { top: '5%', left: '3%', transform: 'rotate(-8deg)' }, m: true },
  { id: 'art-bowl', w: 170, style: { top: '3%', right: '6%', transform: 'rotate(7deg)' }, m: true },
  { id: 'art-nigiri', w: 200, style: { top: '40%', left: '1.5%', transform: 'rotate(9deg)' } },
  { id: 'art-ramen', w: 210, style: { top: '41%', right: '1%', transform: 'rotate(-6deg)' } },
  { id: 'art-bowl', w: 150, style: { bottom: '4%', left: '8%', transform: 'rotate(-6deg)' }, m: true },
  { id: 'art-maki', w: 150, style: { bottom: '5%', right: '7%', transform: 'rotate(10deg)' }, m: true },
  { id: 'art-nigiri', w: 150, style: { bottom: '3%', left: '42%', transform: 'rotate(-4deg)' } },
  { id: 'art-ramen', w: 160, style: { top: '1%', left: '38%', transform: 'rotate(4deg)' } },
];

export const LoginArt: React.FC = () => (
  <div className="login-art" aria-hidden="true">
    <Defs />
    {pieces.map((p, i) => {
      const [vw, vh] = VB[p.id];
      return (
        <svg key={i} className={`art${p.m ? '' : ' art-hide-m'}`} width={p.w} height={Math.round((p.w * vh) / vw)} viewBox={`0 0 ${vw} ${vh}`} style={p.style}>
          <use href={`#${p.id}`} width={vw} height={vh} />
        </svg>
      );
    })}
  </div>
);
