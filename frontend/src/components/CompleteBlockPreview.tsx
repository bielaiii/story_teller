import { useLayoutEffect, useRef } from "react";
import { RenderedMarkdown } from "./RenderedMarkdown";

export function previewBlockHiddenStates(bottoms: number[], availableBottom: number): boolean[] {
  let overflowing = false;
  return bottoms.map((bottom, index) => {
    const hidden = overflowing || (index > 0 && bottom > availableBottom);
    if (bottom > availableBottom) overflowing = true;
    return hidden;
  });
}

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
      const hiddenStates = previewBlockHiddenStates(
        blocks.map((block) => block.getBoundingClientRect().bottom),
        availableBottom,
      );
      blocks.forEach((block, index) => { block.hidden = hiddenStates[index]; });
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
