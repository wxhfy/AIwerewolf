"use client";

import { useRef } from "react";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";
import styles from "./AnimatedWerewolfBackground.module.css";

if (typeof window !== "undefined") {
  gsap.registerPlugin(useGSAP);
}

const starPositions = [
  { left: "10%", top: "18%" },
  { left: "18%", top: "32%" },
  { left: "24%", top: "14%" },
  { left: "32%", top: "24%" },
  { left: "41%", top: "16%" },
  { left: "48%", top: "31%" },
  { left: "56%", top: "18%" },
  { left: "64%", top: "27%" },
  { left: "71%", top: "13%" },
  { left: "78%", top: "34%" },
  { left: "84%", top: "20%" },
  { left: "89%", top: "43%" },
  { left: "15%", top: "48%" },
  { left: "36%", top: "39%" },
  { left: "61%", top: "45%" },
  { left: "74%", top: "51%" },
];

function getLayer(root: HTMLDivElement, name: string) {
  return root.querySelector<HTMLElement>(`[data-bg-layer="${name}"]`);
}

export function AnimatedWerewolfBackground() {
  const scopeRef = useRef<HTMLDivElement>(null);

  useGSAP(() => {
    const root = scopeRef.current;
    if (!root) return;

    const media = gsap.matchMedia();
    media.add("(prefers-reduced-motion: no-preference)", () => {
      const baseMountains = getLayer(root, "base");
      const moon = getLayer(root, "moon");
      const fogBack = getLayer(root, "fogBack");
      const fogFront = getLayer(root, "fogFront");
      const wolf = getLayer(root, "wolf");
      const treesFront = getLayer(root, "treesFront");
      const stars = Array.from(root.querySelectorAll<HTMLElement>("[data-bg-star]"));

      gsap.fromTo(baseMountains, { scale: 1, y: 0 }, {
        scale: 1.025,
        y: -6,
        duration: 24,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });

      gsap.fromTo(moon, { scale: 1, opacity: 0.72 }, {
        scale: 1.06,
        opacity: 0.95,
        duration: 8,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });

      gsap.fromTo(fogBack, { x: -40, y: 0, opacity: 0.25 }, {
        x: 40,
        y: -8,
        opacity: 0.45,
        duration: 32,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });

      gsap.fromTo(fogFront, { x: 60, y: 4, opacity: 0.35 }, {
        x: -60,
        y: -6,
        opacity: 0.58,
        duration: 38,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });

      gsap.fromTo(wolf, { y: 0, scale: 1, opacity: 0.72 }, {
        y: -4,
        scale: 1.015,
        opacity: 0.88,
        duration: 10,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });

      gsap.fromTo(treesFront, { scale: 1.01, y: 0 }, {
        scale: 1.025,
        y: -3,
        duration: 28,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });

      stars.forEach((star, index) => {
        gsap.fromTo(star, { opacity: 0.18, scale: 0.8 }, {
          opacity: index % 3 === 0 ? 0.48 : 0.34,
          scale: 1.4,
          duration: 3 + (index % 5) * 0.55,
          delay: index * 0.28,
          repeat: -1,
          yoyo: true,
          ease: "sine.inOut",
        });
      });
    });

    return () => media.revert();
  }, { scope: scopeRef });

  return (
    <div ref={scopeRef} className={styles.werewolfBackground} aria-hidden="true">
      <img
        className={`${styles.layer} ${styles.baseMountains}`}
        data-bg-layer="base"
        src="/images/werewolf-bg/base-mountains.webp"
        alt=""
        draggable={false}
      />
      <img
        className={`${styles.layer} ${styles.moon}`}
        data-bg-layer="moon"
        src="/images/werewolf-bg/moon.webp"
        alt=""
        draggable={false}
      />
      <div className={styles.stars}>
        {starPositions.map((position, index) => (
          <span
            key={`${position.left}-${position.top}`}
            className={styles.star}
            data-bg-star
            style={{
              left: position.left,
              top: position.top,
              width: index % 4 === 0 ? 3 : 2,
              height: index % 4 === 0 ? 3 : 2,
            }}
          />
        ))}
      </div>
      <img
        className={`${styles.layer} ${styles.fogBack}`}
        data-bg-layer="fogBack"
        src="/images/werewolf-bg/fog.webp"
        alt=""
        draggable={false}
      />
      <img
        className={`${styles.layer} ${styles.wolf}`}
        data-bg-layer="wolf"
        src="/images/werewolf-bg/wolf.webp"
        alt=""
        draggable={false}
      />
      <img
        className={`${styles.layer} ${styles.treesFront}`}
        data-bg-layer="treesFront"
        src="/images/werewolf-bg/trees-front.webp"
        alt=""
        draggable={false}
      />
      <img
        className={`${styles.layer} ${styles.fogFront}`}
        data-bg-layer="fogFront"
        src="/images/werewolf-bg/fog.webp"
        alt=""
        draggable={false}
      />
      <div className={styles.centralClarity} />
      <div className={styles.vignette} />
    </div>
  );
}
