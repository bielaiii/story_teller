import { useLayoutEffect, useRef } from "react";
import { RenderedMarkdown } from "./RenderedMarkdown";

export function CompleteBlockPreview({ source, className = "" }: { source: string; className?: string }) {
  const hostRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const host = hostRef.current;
    const rendered = host?.firstElementChild as HTMLElement | null;
    if (!host || !rendered) return;
    let frame = 0;
    const fitCompleteBlocks = () => {
      frame = 0;
      const blocks = [...rendered.children] as HTMLElement[];
      blocks.forEach((block) => { block.hidden = false; });
      const availableBottom = host.getBoundingClientRect().bottom + .5;
      let overflowing = false;
      for (const block of blocks) {
        if (overflowing || block.getBoundingClientRect().bottom > availableBottom) {
          overflowing = true;
          block.hidden = true;
        }
      }
      host.dataset.measured = "true";
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(fitCompleteBlocks);
    };
    const observer = new ResizeObserver(schedule);
    observer.observe(host);
    schedule();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [source]);

  return <div ref={hostRef} className="complete-block-preview"><RenderedMarkdown source={source} className={className} /></div>;
}
