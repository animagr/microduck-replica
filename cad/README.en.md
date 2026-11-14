# CAD and Models Consolidated in the Companion Repo

**English** · [简体中文](README.md)

**Please download structural parts, assemblies, SolidWorks / STEP source files and print projects from [fanhao375/microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad).**

That repo is the single maintained entry point for the models and includes version selection, the assembly BOM, component drawings and installation instructions. As of 2026-09-28, Feetech HD-1910 is at [v2.1](https://github.com/fanhao375/microduck-replica-cad/releases/tag/v2.1) and XL330 is at [v1.1](https://github.com/fanhao375/microduck-replica-cad/releases/tag/v1.1). Check the servo type and the specific attachment version before downloading; for printing notes see [print/README](../print/README.md).

The 16 STLs previously in this directory were assembly previews generated from the upstream MJCF and were not kept in sync with the latest physical CAD; they were removed on 2026-09-28. Check Git history if you need to trace them; get the latest files from the companion repo.

The analysis renders in this repo's `assembly-drawings/`, the training models and the web debugging models still use upstream geometry and should not be used as the basis for machining or printing the latest structural parts. The [export script](../scripts/export_assembly_stl.py) is only for analyzing the upstream models and by default writes to the ignored `analysis-output/cad-upstream/`.

**English:** CAD assemblies, mechanical parts and print files now have one maintained source: [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad). The old upstream assembly-preview STLs were removed from this directory. Simulation and visualization meshes retained elsewhere are not manufacturing files.
