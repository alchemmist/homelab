This is `packages/github` from alchemmist/quality-graph, with its MIT license.
The last published source revision used here was `95762edd93bb3bfeb459f787c8fc71ef7154916c`.
Local source revision `151aab3128b4cfa5219263797cee6abf546b9c81` changes the
compiler's YAML emitter and publisher templates to meet strict lint while
preserving loaded workflow values. Compare this directory directly against
`git archive 95762edd93bb3bfeb459f787c8fc71ef7154916c:packages/github` in an
upstream clone. The only packaging adaptation is removing the upstream uv
workspace source declaration; the root project pins core instead. `uv sync
--locked` builds this provider from source. This is not the privileged publisher
Action; its SHA remains separately pinned in `qg.yaml`.
