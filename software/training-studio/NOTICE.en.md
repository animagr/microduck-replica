# Sources and licenses

**English** · [简体中文](NOTICE.md)

- The original code of the training studio follows the repo's [Apache-2.0](../../LICENSE) license, and the documentation follows the documentation license in the root [NOTICE](../../NOTICE.md). No existing engine has been copied or rewritten.
- The UI reuses the black-white-yellow duck logo, colors and component rules of this repo's Studio web console.
- The 3D preview reuses `../studio/web/duck3d.js` and `../studio/web/model/`. The model is derived from Pollen Robotics' publicly released simulation geometry and keeps the **CC BY-NC-SA** terms per the repo root NOTICE; it is not new CAD for physical printing. For historical conversion notes see [Studio model source](../studio/web/model/NOTICE.md); the root NOTICE is authoritative for the full license boundaries.
- The web page reuses the already-distributed Preact, htm and Three.js, and does not download from any external CDN. Preact and Three.js are MIT, htm is Apache-2.0; the license texts are in [`../studio/web/vendor/licenses/`](../studio/web/vendor/licenses/).
- The HD1910 training recipe, the Pollen Robotics training engine, LuwuDynamics' 1910 M6 parameters and Rhoban/BAM each keep their original attribution and license; see [`../training/UPSTREAM.md`](../training/UPSTREAM.md).
- This training studio does not include front-end code, brand icons or screenshots from other training products. Sample actions and synthetic data are for UI demonstration only.
