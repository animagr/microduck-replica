# Model source

**English** · [简体中文](NOTICE.md)

`model.json` + `meshes.bin` were converted by `../build_model.py` from [apirrone/microduck_rl](https://github.com/apirrone/microduck_rl)'s
`src/mjlab_microduck/robot/microduck/robot_allcollisions.xml` and its `assets/*.stl` (snapshot of 2026-09-17);
that repository is under the Apache License 2.0. The meshes are exported from Pollen Robotics' official Microduck CAD. Only the visible exterior is kept; internal parts such as circuit boards and bearings are removed,
and the vertices are int16-quantized.
