---
name: frontend-design
description: Create bold, high-end, production-grade frontend interfaces with the mindset of a professional UI/UX designer and frontend engineer. This skill is used when the user asks to design or redesign web interfaces (components, pages, dashboards, or applications) that must feel intentional, distinctive, and non-generic. Implement real working code with exceptional attention to aesthetic details and creative choices.
---

# Frontend Design Skill

Create distinctive, production-grade frontend interfaces that avoid generic "AI slop" aesthetics. Implement real working code with exceptional attention to aesthetic details and creative choices.

## Design Thinking Process
Before coding, understand the context and commit to a BOLD aesthetic direction:
- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick a clear extreme: brutally minimal, maximalist chaos, luxury/refined, brutalist/raw, retro-futuristic, organic/soft, etc.
- **Constraints**: Technical requirements (framework, performance, accessibility)
- **Differentiation**: What makes this UNFORGETTABLE?

CRITICAL: Choose a clear conceptual direction and execute it with precision. Bold maximalism and refined minimalism both work - the key is intentionality, not intensity.

Then implement working code (HTML/CSS/JS, React, Vue, etc.) that is:
- Production-grade and functional
- Visually striking and memorable
- Cohesive with a clear aesthetic point-of-view
- Meticulously refined in every detail

## Frontend Aesthetics Guidelines
Focus on these core elements:
- **Typography**: Choose distinctive fonts. Avoid Arial/Inter/Roboto. Pair a bold display font with refined body font.
- **Color & Theme**: Commit to cohesive aesthetic. Use CSS variables. Dominant colors with sharp accents outperform timid palettes.
- **Motion**: High-impact animations for page load with staggered reveals. Use CSS @keyframes for HTML, Framer Motion for React.
- **Spatial Composition**: Unexpected layouts. Asymmetry. Overlap. Diagonal flow. Grid-breaking elements.
- **Backgrounds & Visual Details**: Create atmosphere with gradient meshes, noise textures, patterns, layered transparencies, shadows.

NEVER use generic AI aesthetics: Inter/Roboto/Arial fonts, purple gradients on white, predictable layouts, cookie-cutter design lacking context-specific character. No design should be the same. NEVER converge on common choices.

IMPORTANT: Match code complexity to vision. Maximalist = elaborate animations. Minimalist = restraint and precision.

## Design Process
1. **Discovery**: Understand requirements, audience, constraints → Define 3 key visual principles
2. **Concept**: Choose aesthetic direction → Select fonts (1-2), colors (3-5), spacing scale
3. **Implement**: Design tokens → Semantic HTML → Visuals → Motion → Polish
4. **Verify**: Accessibility, responsiveness, performance

## Design Token Detection
Before implementing, check if user's project has existing design tokens:
- Check: `tailwind.config.js`, CSS `:root` variables, `theme.js`, `styles/variables.css`, styled-components themes
- If found: Extract and use existing colors/typography/spacing. Follow naming conventions. Only add new tokens for gaps.
- If not found: Create inline design tokens matching chosen aesthetic.

## Accessibility (Non-Negotiable)
WCAG 2.1 AA required. Creative freedom in aesthetics, NOT accessibility.
- **Contrast**: 4.5:1 text, 3:1 UI
- **Keyboard**: Tab/Enter/Escape work, visible focus, no traps
- **Semantic HTML**: h1-h6 hierarchy, landmarks, alt text
- **Motion**: `@media (prefers-reduced-motion: reduce)` for all animations
- **Forms**: Labels for all inputs, clear error messages

Rule: Accessibility wins over aesthetics.

## Responsive Design
- Mobile-first approach
- Breakpoints: 640px (sm), 768px (md), 1024px (lg), 1280px (xl)
- Fluid typography: `clamp(1rem, 0.5rem + 2vw, 2rem)`
- CSS Grid/Flexbox over fixed widths
- Touch targets: 44x44px minimum
- Test on real device sizes

## Technical Patterns
### Design Tokens
Follow this structure:
```css
:root {
  /* Fonts */
  --font-display: 'Your Display Font', sans-serif;
  --font-body: 'Your Body Font', sans-serif;
  
  /* Colors */
  --color-primary: #xxxxxx;
  --color-secondary: #xxxxxx;
  --color-accent: #xxxxxx;
  --color-background: #xxxxxx;
  --color-text: #xxxxxx;
  
  /* Spacing */
  --spacing-xs: 0.25rem;
  --spacing-sm: 0.5rem;
  --spacing-md: 1rem;
  --spacing-lg: 2rem;
  --spacing-xl: 4rem;
  
  /* Radius */
  --radius-sm: 0.25rem;
  --radius-md: 0.5rem;
  --radius-lg: 1rem;
  
  /* Shadows */
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);
  
  /* Animation */
  --transition-fast: 150ms ease-out;
  --transition-normal: 300ms ease-out;
  --transition-slow: 500ms ease-out;
}
```

### Animations
- HTML/CSS: `@keyframes` with `animation-delay` for staggered effects
- React: Framer Motion for complex animations, CSS for simple ones
- Only animate `transform` and `opacity` for performance

### Code Quality
- Semantic HTML (header, nav, main, article, section)
- BEM class naming or Tailwind utilities
- Clean, well-structured code with logical component organization
- Performance optimized: lazy loading, code splitting where appropriate

## Output Requirements
- First state the aesthetic direction you've chosen and why it fits the use case
- Provide complete, runnable code that can be executed immediately
- Include all necessary dependencies (CDN links for CSS/JS libraries, import statements)
- Add comments for key design decisions and creative choices
- Ensure the final result is visually impressive and meets all accessibility requirements
