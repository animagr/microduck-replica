# Managing build caches on the development computer

**English** · [简体中文](开发环境编译缓存管理.md)

This is a disk space issue on the computer when building from source. Ordinary users who download the image or install a software update package do not generate a full Rust build cache on their computer.

Cargo puts the final programs and intermediate files in the target/build directory. Intermediate files speed up the next build, but do not need to be delivered with the program. At present Cargo's automatic garbage collection mainly covers the downloaded global cache and cannot replace managing the target build directory. See [Cargo build cache](https://doc.rust-lang.org/cargo/reference/build-cache.html) and [Cargo cache configuration](https://doc.rust-lang.org/cargo/reference/config.html#cache) for details.

## Project retention rules

1. Day-to-day development uses a fixed pair of caches, one for the host and one for ARM, rather than keeping a whole target per commit long-term.
   `CARGO_TARGET_DIR` is set through the project's build commands, without changing the global Cargo configuration of other projects.
2. Independent reproducible verification still uses two isolated temporary targets. After verification passes, put the binaries, source version,
   hashes and test records into a separate release directory, then clear the temporary object, incremental, Zig and temporary file caches.
3. The two everyday caches are checked against a budget of 20 GiB each, 40 GiB in total; when over budget or when free space on any relevant disk
   drops below 20 GiB, first stop new builds and list what can be reclaimed. The budget is this project's maintenance rule,
   not something Cargo enforces by itself. An idle old cache may be rebuilt entirely; you cannot dodge the space check by constantly switching disks.
4. Released software, rollback packages, signing material, original models, user calibration and fixed verification baselines are not caches.
   Temporary expansion directories used during image creation must also be kept separate from the official image and cleaned up according to a list after the acceptance check.
5. Before cleaning, check current build locks, process references, mount points and actual absolute paths; source directories, link targets,
   unrecognized directories and active caches are never deleted automatically. If an old directory still holds programs that tools depend on, keep it first
   or archive it separately and verify the hashes.

## Manually cleaning your own Cargo projects

In a project confirmed to be idle, you can use Cargo's own clean command. If a shared target is specified,
you must explicitly check which builds still use it; cleaning makes later builds regenerate the intermediate files.

```sh
cargo clean --manifest-path /your/source/Cargo.toml --target-dir /your/dedicated/build/cache
```

Short-term verification can use `CARGO_INCREMENTAL=0` to reduce incremental usage when compiling only once; for everyday
development, keeping one budgeted set of incremental caches is enough. Release packages should not carry target, temporary build directories or
the maintainer's personal files.

## With WSL, also check the host disk

After deleting files inside Linux, check both the free space in Linux and the actual space on the Windows drive.
The virtual disk file may still be large. Reclaiming host space is a separate maintenance task; do not delete ext4.vhdx directly.

Before reclaiming, check `wsl --version` and `wsl --help` on your machine. For example, with WSL 3.0.3 used this time,
`--manage <distro> --compact` stops the target distro and runs an offline check with automatic repair;
it is not suitable as a command to run silently after every build. First finish active tasks and confirm the maintenance scope, then
compare the virtual disk size with the free space on the host, and re-verify key files. See [Microsoft's disk management guide](https://learn.microsoft.com/en-us/windows/wsl/disk-space)
and [the offline check implementation in this machine's WSL version](https://github.com/microsoft/WSL/blob/15ea3b3846c5f18318722d1381186b2ff6ed72eb/src/linux/init/main.cpp#L2986).

This round of software updates keeps using the existing update entry point of the Oct 27 release; there is no need to make a new image for every feature update.
