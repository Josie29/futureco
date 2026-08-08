// cytoscape-fcose ships no types. It is registered once via cytoscape.use and
// referenced only by layout name after that, so the extension itself needs no
// surface beyond "this is a cytoscape extension".
declare module "cytoscape-fcose" {
  import type { Ext } from "cytoscape"
  const fcose: Ext
  export default fcose
}
