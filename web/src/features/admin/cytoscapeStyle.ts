import type { StylesheetStyle } from "cytoscape"
import { NodeLabel, RelType } from "@/types/graph"

/**
 * Per-label appearance.
 *
 * Colour carries the node type, which is a second job for colour on top of the
 * console's rule — so the palette stays inside the brand and red keeps its one
 * meaning. Injury and Condition are red because they *are* the safety story,
 * the same red-wash the constraint pills use.
 *
 * Hue is not the channel doing the work. Only three types are actually
 * coloured — Member and Goal in cobalt, Injury and Condition in red-wash — and
 * the remaining five separate by *weight* instead: black fill, white with a
 * black outline, white with a faint outline, filled grey with no outline, pale
 * grey with grey text. That ordering survives greyscale, which a five-hue
 * palette would not.
 *
 * Nothing here is legible by appearance alone either: every node prints its
 * caption, the legend chips are named, and selecting one names its type.
 */
interface LabelStyle {
  bg: string
  border: string
  text: string
  /** Box padding around the caption. Nodes size to their text, so this is the
   *  only weight control — a fixed width would clip "Return to pain-free
   *  squatting after left-knee flare-up" or leave "hip" swimming. */
  padding: number
  borderWidth: number
}

export const LABEL_STYLE: Record<NodeLabel, LabelStyle> = {
  [NodeLabel.MEMBER]: {
    bg: "#2b3fe8",
    border: "#2b3fe8",
    text: "#ffffff",
    padding: 11,
    borderWidth: 2.5,
  },
  [NodeLabel.GOAL]: {
    bg: "#ecedfc",
    border: "#2b3fe8",
    text: "#0d0d0f",
    padding: 9,
    borderWidth: 1.5,
  },
  [NodeLabel.EXERCISE]: {
    bg: "#0d0d0f",
    border: "#0d0d0f",
    text: "#ffffff",
    padding: 8,
    borderWidth: 1.5,
  },
  [NodeLabel.MUSCLE]: {
    bg: "#ffffff",
    border: "#0d0d0f",
    text: "#0d0d0f",
    padding: 7,
    borderWidth: 1.5,
  },
  [NodeLabel.EQUIPMENT]: {
    bg: "#ffffff",
    border: "#c3c3c8",
    text: "#0d0d0f",
    padding: 7,
    borderWidth: 1,
  },
  [NodeLabel.MOVEMENT_PATTERN]: {
    bg: "#e2e2dc",
    border: "#e2e2dc",
    text: "#0d0d0f",
    padding: 7,
    borderWidth: 1,
  },
  [NodeLabel.ANATOMICAL_STRUCTURE]: {
    bg: "#f6f6f3",
    border: "#9a9aa1",
    text: "#6b6b73",
    padding: 7,
    borderWidth: 1,
  },
  [NodeLabel.INJURY]: {
    bg: "#fbecea",
    border: "#cf3328",
    text: "#0d0d0f",
    padding: 9,
    borderWidth: 2,
  },
  [NodeLabel.CONDITION]: {
    bg: "#fbecea",
    border: "#cf3328",
    text: "#0d0d0f",
    padding: 9,
    borderWidth: 2,
  },
}

/** The two edges that carry a safety decision, drawn in the one red. */
const CLINICAL: RelType[] = [RelType.CONTRAINDICATES, RelType.CAUTIONS]

export function buildStylesheet(): StylesheetStyle[] {
  const perLabel = Object.entries(LABEL_STYLE).flatMap(([label, s]) => [
    {
      selector: `node[label = "${label}"]`,
      style: {
        "background-color": s.bg,
        "border-color": s.border,
        "border-width": s.borderWidth,
        padding: s.padding,
        color: s.text,
      },
    } as StylesheetStyle,
  ])

  return [
    {
      selector: "node",
      style: {
        label: "data(caption)",
        "font-family": "Archivo Variable, system-ui, sans-serif",
        "font-size": 9,
        "font-weight": 600,
        "text-valign": "center",
        "text-halign": "center",
        // Nodes size to their caption, so long goal text wraps into a taller
        // pill instead of spilling across its neighbours.
        shape: "round-rectangle",
        width: "label",
        height: "label",
        "text-wrap": "wrap",
        "text-max-width": "104px",
        "transition-property": "opacity",
        "transition-duration": 150,
      },
    },
    ...perLabel,
    {
      selector: "edge",
      style: {
        width: 1.2,
        "line-color": "#c3c3c8",
        "target-arrow-color": "#c3c3c8",
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.7,
        "curve-style": "bezier",
        opacity: 0.8,
      },
    },
    {
      selector: CLINICAL.map((r) => `edge[rel = "${r}"]`).join(", "),
      style: { "line-color": "#cf3328", "target-arrow-color": "#cf3328", width: 2, opacity: 1 },
    },
    // Root and selection are drawn as overlays rather than borders. Border
    // colour and width are how a node says what type it is — a selected
    // Equipment with a black outline would read as a Muscle, and the root with
    // a cobalt outline would read as a Goal.
    {
      selector: "node.root",
      style: { "overlay-color": "#2b3fe8", "overlay-opacity": 0.18, "overlay-padding": 7 },
    },
    {
      selector: "node:selected",
      style: { "overlay-color": "#0d0d0f", "overlay-opacity": 0.16, "overlay-padding": 5 },
    },
    // Labels are hidden on edges until one is hovered — 454 of them at once is
    // noise, but the single one under the pointer is the whole question.
    {
      selector: "edge.hovered",
      style: {
        label: "data(rel)",
        "font-family": "Spline Sans Mono Variable, ui-monospace, monospace",
        "font-size": 8,
        color: "#0d0d0f",
        "text-background-color": "#ffffff",
        "text-background-opacity": 0.9,
        "text-background-padding": "2px",
        width: 2.4,
        opacity: 1,
      },
    },
    { selector: ".dimmed", style: { opacity: 0.12 } },
    // Marks a node with neighbours the view has not pulled in yet.
    {
      selector: "node.unexpanded",
      style: { "border-style": "dashed" },
    },
  ]
}
