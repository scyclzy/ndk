# Build System Maintainers Guide

The latest version of this document is available at
https://android.googlesource.com/platform/ndk/+/master/docs/BuildSystemMaintainers.md.

The purpose of this guide is to instruct third-party build system maintainers in
adding NDK support to their build systems. This guide will not be useful to most
NDK users. NDK users should start with [Building Your Project].

Note: This guide is written assuming Linux is the host OS. Mac should be no
different, and the only difference on Windows is that file extensions for
executables and scripts will differ.

[Building Your Project]: https://developer.android.com/ndk/guides/build

[TOC]

## Introduction

The NDK uses [Clang] as its C/C++ compiler and [Binutils] for linking,
archiving, and object file manipulation. Binutils provides both BFD and gold for
linking. LLVM's [LLD] is also included for testing. AOSP uses LLD by default for
most projects and the NDK is expected to move to it in the future.

[Binutils]: https://www.gnu.org/software/binutils
[Clang]: https://clang.llvm.org/
[LLD]: https://lld.llvm.org/

### Architectures
[Architectures]: #architectures

Note: In general an architecture may have multiple ABIs. An ABI (application
binary interface) is different from an architecture in that it also specifies a
calling convention, size and alignment of types, and other implementation
details. For Android, each architecture supports only one ABI.

Android supports multiple architectures: ARM32, ARM64, x86, and x86_64. NDK
applications must build libraries for every architecture they support. 64-bit
devices usually also support the 32-bit variant of their architecture, but this
may not always be the case. While in general this means that an app with only
32-bit libraries can run on 64-bit capable devices, the 64-bit ABI will have
improved performance.

This document will make use of `<arch>`, `<ABI>`, and `<triple>` in describing
paths and arguments. The values of these variables for each architecture are as
follows except where otherwise noted:

| Name         | arch    | ABI         | triple                |
| ------------ | ------- | ----------- | --------------------- |
| 32-bit ARMv7 | arm     | armeabi-v7a | arm-linux-androideabi |
| 64-bit ARMv8 | aarch64 | aarch64-v8a | aarch64-linux-android |
| 32-bit Intel | x86     | x86         | i686-linux-android    |
| 64-bit Intel | x86_64  | x86_64      | x86_64-linux-android  |

Note: Strictly speaking ARMv7 with [NEON] is a different ABI from ARMv7 without
NEON, but it is not a *system* ABI. Both NEON and non-NEON ARMv7 code uses the
ARMv7 system and toolchains.

To programatically determine the list of supported ABIs, their bitness, as well
as their deprecation status and whether or not it is recommended to build them
by default, use `<NDK>/meta/abis.json`.

### Thumb

32-bit ARM can be built using either the [Thumb] or ARM instruction sets. Thumb
code is smaller but may perform worse than ARM. However, smaller code makes more
effective use of a processor's instruction cache, so benchmarking is necessary
to determine which is more effective for a given application. ndk-build and the
NDK's CMake toolchain file generate Thumb code by default.

The ARM or Thumb instruction sets are selected by passing `-marm` or `-mthumb`
to Clang respectively. By default, Clang will generate ARM code as opposed to
Thumb for the `armv7a-linux-androideabi` target.

Note: For ARMv7, Thumb-2 is used. Android no longer supports ARMv5, but if your
build system mistakenly targets ARMv5 the less efficient Thumb-1 will be used.

[Thumb]: https://en.wikipedia.org/wiki/ARM_architecture#Thumb-2

### NEON

Most ARM Android devices support [NEON]. This is supported by all 64-bit ARM
devices and nearly all 32-bit ARM devices running at least Android Marshmallow
(API 23). The [Android CDD] has required NEON support since that version, but it
is possible that extant devices that were upgraded to Marshmallow do not include
NEON support.

Enabling NEON can significantly improve application performance.

To enable NEON, pass `-mfpu=neon` when compiling.

Note: The NDK's supported build systems (ndk-build and the CMake toolchain file)
automatically enable NEON for API levels 23 (Marshmallow) and higher.

[Android CDD]: https://source.android.com/compatibility/cdd
[NEON]: https://developer.arm.com/technologies/neon

### OS Versions
[OS Versions]: #os-versions

As users are distributed over a wide variety of Android OS versions (see the
[Distribution dashboard]), applications have a minimum and maximum supported
version, as well as a targeted version. These are `minSdkVersion`,
`maxSdkVersion`, and `targetSdkVersion` respectively. See the [uses-sdk]
documentation for more information.

For NDK code, the only relevant value is the minimum supported version. Any time
this doc refers to an API level, OS version, or target version, it is referring
to the application's `minSdkVersion`.

The API level targeted by an NDK application determines which APIs will be
exposed for use by the application. APIs that are not present in the targeted
API level cannot be linked directly, but may be accessed via `dlsym`. An NDK
application running on a device with an API level lower than the target will
often not load at all. If it does load, it may not behave as expected. This is
not a supported configuration.

The major/minor version number given to an Android OS has no meaning when it
comes to determining its API level. See the table in the [Build numbers]
document to map Android code names and version numbers to API levels.

Note: Not every API level includes new NDK APIs. If there were no new NDK APIs
for the given API level, there is no library directory for that API level. In
that case, the build system should select the closest available API that is
below the target API level. For example, applications with a `minSdkVersion` of
20 should use API 19 for their NDK target.

To programatically determine the list of supported API levels as well as aliases
that are accepted by ndk-build and CMake, see `<NDK>/meta/platforms.json`.

Note: In some contexts the API level may be referred to as a platform. In this
document an API level is always an integer, and a platform takes the form of
`android-<API level>`. The latter format is not specifically used anywhere in
the NDK toolchain, but is used to specify target API levels for ndk-build and
CMake.

Note: As a new version of the Android OS approaches release, previews and betas
of that OS will be released and an NDK will be released that can make use of the
new APIs. Targeting a preview API level is no different than targeting a
released API level, with the exception that applications built targeting preview
releases should not be shipped to production. Consult
`<NDK>/meta/platforms.json` to determine the API level for a preview release.

[Build numbers]: https://source.android.com/setup/start/build-numbers
[Distribution dashboard]: https://developer.android.com/about/dashboards/
[uses-sdk]: https://developer.android.com/guide/topics/manifest/uses-sdk-element

## Clang

Clang is installed to `<NDK>/toolchain/bin/clang`. The C++ compiler is installed
as `clang++` in the same directory. `clang++` will make C++ headers available
when compiling and will automatically link the C++ runtime libraries when
linking.

`clang` should be used when compiling C source files, and `clang++` should be
used when compiling C++ source files. When linking, `clang` should be used if
the binary being linked contains no C++ code (i.e. none of the object files
being linked were generated from C++ files) and `clang++` should be used
otherwise. Using `clang++` ensures that the C++ standard library is linked.

### Target Selection

[Cross-compilation] targets can be selected in one of two ways.

First, the `--target` flag can be used (see the [Clang User Manual] for more
details on Clang's supported arguments). The value passed is a Clang target
triple suffixed with an Android API level. For example, to target API 26 for
32-bit ARM, use `--target armv7a-linux-androideabi26`.

Note: "armv7a" should be used rather than simply "arm" when specifying targets
for Clang to generate ARMv7 code rather than the slower ARMv5 code. Specifying
ARMv5 and thumb code generation will result in Thumb-1 being generated rather
than Thumb-2, which is less efficient.

Second, a target-specific Clang can be used. In addition to the `clang` and
`clang++` binaries, there are also `<triple><API-level>-clang` and
`<triple><API-level>-clang++` scripts. For example, to target API 26 32-bit ARM,
invoke `armv7a-linux-androideabi26-clang` or
`armv7a-linux-androideabi26-clang++` instead of `clang` or `clang++`.

Note: Target specific Clangs are currently implemented as shell scripts. Linux
and Mac NDKs have Bash scripts, Windows includes Bash scripts to support Cygwin
and WSL but also batch scripts (with `.cmd` extensions`) for Windows command
line support. For large numbers of relatively small source files, the additional
overhead caused by these scripts may be noticably slower than using `--target`,
especially on Windows where `CreateProcess` is slower than `fork`.

For more information on Android targets, see the [Architectures] and [OS
Versions] sections.

[Clang User Manual]: https://clang.llvm.org/docs/UsersManual.html
[Cross-compilation]: https://en.wikipedia.org/wiki/Cross_compiler

## Linkers

Gold is used by default for most architectures, but BFD is used for AArch64 as
Gold emits broken debug information for that architecture (see [Issue 70838247]
for more details).

Note: It is usually not necessary to invoke the linkers directly since Clang
will do so automatically. Clang will also automatically link CRT objects and
default libraries and set up other target-specific options, so it is generally
better to use Clang for linking.

The default linkers are installed to `<NDK>/toolchain/bin/<triple>-ld` and
`<NDK/toolchain/<triple>/bin/ld`. To use BFD or gold explicitly, use `ld.bfd` or
`ld.gold` from the same locations. `ld.lld` is not installed to the triple
directory and is not triple-prefixed, but rather is only installed as
`<NDK>/toolchain/bin/ld.lld` because the one binary supports all ABIs.

[Issue 70838247]: https://issuetracker.google.com/70838247

## Sysroot

The Android sysroot is installed to `<NDK>/toolchain/sysroot` and contains the
headers, libraries, and CRT object files for each Android target.

Headers can be found in the `usr/include` directory of the sysroot. Target
specific include files are installed to `usr/include/<triple>`. When using
Clang, it is not necessary to include these directories explicitly; Clang will
automatically select the sysroot. If using a compiler other than Clang, ensure
that the target-specific include directory takes precedence over the
target-generic directory.

Libraries are found in the `usr/lib/<triple>` directory of the sysroot.
Version-specific libraries are installed to `usr/lib/<triple>/<API-level>`. As
with the header files, when using Clang it is not necessary to include these
directories explicitly; the sysroot will be automatically selected. If using a
compiler other than Clang, ensure that the version-specific library directory
takes precedence over the version-generic directory.

## Libraries

The NDK contains three types of libraries. Static libraries have a .a file
extension and are linked directly into app binaries. Shared libraries have a .so
file extension and must be included in the app's APK if used. System stub
libraries are a special type of shared library that should not be included in
the APK. The system stub libraries define the interface of a library that is
provided by the Android OS but contain no implementation. They can be identified
by their .so file extension and their presence in the [system_libs list] in
ndk-build. The entries in this file are a key/value pair that maps library names
to the first API level the library is introduced.

[Issue 801]: https://github.com/android-ndk/ndk/issues/801
[system_libs list]: https://android.googlesource.com/platform/ndk/+/master/meta/system_libs.json

## STL

### libc++

The STL provided by the NDK is [libc++]. Its headers are installed to
`<NDK>/sysroot/usr/include/c++/v1`. To use this STL, use the `-stdlib=libc++`
flag. This STL comes in both a static and shared variant. The shared variant is
used by default. To use the static variant, pass `-static-libstdc++` when
linking. If using the shared variant, libc++_shared.so must be included in the
APK. This library is installed to `<NDK>/sysroot/usr/lib/<triple>`.

Warning: There are a number of things to consider when selecting between the
shared and static STLs. See the [Important Considerations] section of the C++
Support document for more details.

There are version-specific libc++.so and libc++.a libraries installed to
`<NDK>/sysroot/usr/lib/<triple>/<version>`. These are not true libraries but
[implicit linker scripts]. They inform the linker how to properly link the STL
for the given version. Older OS versions may require that a compatibility
library (libandroid_support) be linked with libc++ to provide APIs not available
in those versions. These scripts also handle the inclusion of any libc++
dependencies if necessary. Linker scripts should not be included in the APK.

Build systems should prefer to let Clang link the STL. If not using Clang, the
version scripts should be used. Linking libc++ and its dependencies manually
should only be used as a last resort.

Note: Linking libc++ and its dependencies explicitly may be necessary to defend
against exception unwinding bugs caused by improperly built dependencies on
ARM32 (see [Issue 379]). If not dependent on stack unwinding (the usual reason
being that the application does not make use of C++ exceptions) or if no
dependencies were improperly built, this is not necessary. If needed, link the
libraries as listed in the linker script and be sure to follow the instructions
in [Unwinding].

[Important Considerations]: https://developer.android.com/ndk/guides/cpp-support#important_considerations
[Issue 379]: https://github.com/android-ndk/ndk/issues/379
[implicit linker scripts]: https://sourceware.org/binutils/docs/ld/Scripts.html
[libc++]: https://libcxx.llvm.org/

### System STL

The legacy "system STL" is also included, but it will be removed in a future NDK
release. It is not in fact an STL; it contains only the barest C++ library
support: the C++ versions of the C library headers and basic C++ runtime support
like `new` and `delete`. Its headers are installed to
`<NDK>/toolchain/include/c++/4.9.x` and its library is the libstdc++.so system
stub library. To use this STL, use the `-stdlib=libstdc++` flag.

TODO: Shouldn't it be installed to sysroot like libc++?

Note: The system STL will likely be removed in a future NDK release.

### No STL

To avoid using the STL at all, pass `-nostdinc++` when compiling and
`-nostdlib++` when linking. This is not necessary when using `clang`, only when
using `clang++`.

## Sanitizers

The NDK supports [Address Sanitizer] (ASan). This tool is similar to Valgrind in
that it diagnoses memory bugs in a running application, but ASan is much faster
than Valgrind (roughly 50% performance compared to an unsanitized application).

To use ASan, pass `-fsanitize=address` when both compiling and linking. The
sanitizer runtime libraries are installed to `<NDK>/toolchain/lib64/clang/<clang
version>/lib/linux`. The library is named `libclang_rt.asan-<arch>-android.so`.
This library must be included in the APK. A [wrap.sh] file must also be included
in the APK. Premade wrap.sh files for ASan are installed to `<NDK>/wrap.sh`.

Note: wrap.sh is only available for [debuggable] APKs running on Android Oreo
(API 26) or higher. ASan can still be used devices prior to Oreo but at least
Lollipop (API 21) if the device has been rooted. Direct users to the
[AddressSanitizerOnAndroid] document for instructions on using this method.

[Address Sanitizer]: https://clang.llvm.org/docs/AddressSanitizer.html
[AddressSanitizerOnAndroid]: https://github.com/google/sanitizers/wiki/AddressSanitizerOnAndroid#run-time-flags
[debuggable]: https://developer.android.com/guide/topics/manifest/application-element#debug
[wrap.sh]: https://developer.android.com/ndk/guides/wrap-script

## Required Android Specific Arguments

Note: It is a bug that any of these need to be specified by the build system.
All flags discussed in this section should be automatically selected by Clang,
but they are not yet. Check back in a future NDK release to see if any can be
removed from your build system.

32-bit ARM targets should use `-mfpu=vfpv3-d16` when compiling unless using
[NEON]. This allows the compiler to make use of the FPU.

C++ builds should use `-stdlib=libc++` when using libc++. This flag is used both
when compiling and when linking. This allows the compiler to find the correct
C++ standard headers and libraries.

For x86 targets prior to Android Nougat (API 24), `-mstackrealign` is needed to
properly align stacks for global constructors. See [Issue 635].

All code must be linked with `-Wl,-z,relro`, which causes relocations to be
made read-only after relocation is performed.

Android requires [Position-independent executables] beginning with API 21. Clang
builds PIE executables by default. If invoking the linker directly or not using
Clang, use `-pie` when linking.

[Issue 635]: https://github.com/android-ndk/ndk/issues/635
[Position-independent executables]: https://en.wikipedia.org/wiki/Position-independent_code#Position-independent_executables

## Useful Arguments

### Dependency Management

It is recommended that `-Wl,--exclude-libs,<library file name>` be used for each
static library linked. This causes the linker to give symbols imported from a
static library hidden [visibility]. This prevents a binary from unintentionally
re-exporting an API other than its own. If the intent is to re-export all the
symbols in a static library, `-Wl,--whole-archive <library>
-Wl,--no-whole-archive` should be used to ensure that the whole archive is
preserved. By default, only symbols in used sections will be included in the
linked binary.

If this behavior is not desired for your build system, ensure that these flags
are at least used for libgcc.a and libunwind.a (libunwind is only used for
ARM32). This is necessary to avoid unwinding bugs on ARM32. See [Unwinding] for
more information.

[visibility]: https://gcc.gnu.org/wiki/Visibility

### Controlling Binary Size

To minimize the size of an APK, it may be desirable to use the `-Oz`
optimization mode. This will generate somewhat slower code than `-O2` or `-O3`,
but it will be smaller.

Note: `-Os` behavior is not the same with Clang as it is with GCC. Clang's `-Oz`
behaves similarly to GCC's `-Os`. `-Os` with Clang is a middle ground between
size and speed optimizations.

To aid the linker in removing as much unused code as possible, the compiler
flags `-ffunction-sections` and `-fdata-sections` may be used. These flags
should only be used in conjunction with the `-Wl,--gc-sections` linker flag.
Failing to use `-Wl,--gc-sections` will cause the former flags to *increase*
output size. The linker is only able to discard unused sections, so it can only
discard at per-function or per-variable granularity if each is in its own
section.

While `-Wl,--gc-sections` should always be used, whether or not to enable
`-ffunction-sections` and `-fdata-sections` depends on how the object file being
compiled is expected to be used. If it will be used in a shared library then all
of its [public symbols] will be preserved and the additional overhead of placing
each item in its own section may make the shared library *larger* rather than
smaller. If it will be used only in a static library or an executable then it
will depend on how much of the resulting object file is expected to be unused.

[public symbols]: #dependency-management

### Helpful Warnings

It is recommended that build systems promote the following warnings to errors.
These warnings indicate either a bug or undefined behavior, the latter of which
Clang will usually turn into a bug.

 * `-Werror=return-type`: A non-void function is missing a return statement.
   Clang may "optimize" this function to fall through into the next one.
 * `-Werror=int-to-pointer-cast` and `-Werror=pointer-to-int-cast`: These
   indicate bugs that will affect the 64-bit version of the application.
 * `-Werror=implicit-function-declaration`: Undeclared functions may be inferred
   to have a return type of `int` in C. For functions that return a pointer, the
   return type will be silently truncated to a 32-bit `int`, resulting in bugs
   that will affect the 64-bit version of the application.

For more information on Clang's supported arguments, see the [Clang User
Manual].

## Common Issues

### Unwinding
[Unwinding]: #unwinding

For 32-bit ARM the NDK makes use of two unwinders: libgcc and LLVM's libunwind.
libunwind is needed to provide C++ exception handling support. libgcc is needed
to provide compiler runtime support and as such its unwinder is also seen by the
linker.

These two unwinders are not ABI compatible but do use the same names, so caution
is required to avoid ODR bugs. For 32-bit ARM, the libgcc.a in the NDK is a
linker script that ensures that libunwind is linked before libgcc, causing the
linker to prefer symbols from libunwind to those from libgcc.

As these are static libraries, the symbols will be included in the linked
binary. By default they will be linked with public visibility. If used in a
build system that does not strictly adhere to only linking shared libraries
after all objects and static libraries, the binary being linked may instead load
these symbols from a shared library. If this library was built with the wrong
unwinder, it is possible for one unwinder to call into the other. As they are
not compatible, this will likely result in either a crash or a failed unwind. To
avoid this problem, libraries should always be built with
`-Wl,--exclude-library,libgcc.a` and `-Wl,--exclude-library,libunwind.a` (the
latter is only necessary for 32-bit ARM) to ensure that unwind symbols are not
re-exported from shared libraries.

Even with the above precautions, it is still possible for an improperly built
external dependency to provide an incorrect unwind implementation as described
in the above paragraph. The only way to guarantee protection against this for
libraries built in your build system is to ensure that objects are linked in the
following order:

 1. crtbegin
 2. object files
 3. static libraries
 4. libgcc
 5. shared libraries
 6. crtend

Unless using `-nostdlib` when linking, crtend and crtbegin will be linked
automatically by Clang. Linking libraries in the order above will require
`-nostdlib++` when using libc++.

## Windows Specific Issues

### Command Line Length Limits

Command line length limits on Windows are short enough that they can pose
problems when building large projects. Commands executed via cmd.exe are limited
to [8,191 characters] and commands executed with `CreateProcess` are limited to
[32,768 characters].

To work around these issues, Clang, the linkers, and the archiver all accept a
response file that specifies the input files in place of specifying each input
explicitly on the command line. Response files are identified on the command
line with a "@" prefix and are formatted as space separated arguments. For
example:

    $ ar crsD liba.a @inputs.rsp

If the contents of `inputs.rsp` are `a.o b.o c.o` then `ar` will insert `a.o`,
`b.o`, and `c.o` into `liba.a`.

[8,191 characters]: https://support.microsoft.com/en-us/help/830473/command-prompt-cmd-exe-command-line-string-limitation
[32,768 characters]: https://docs.microsoft.com/en-us/windows/desktop/api/processthreadsapi/nf-processthreadsapi-createprocessa

### Path Length Limits

Windows paths are limited to 260 characters, including the drive letter, colon,
backslash, and terminating null. See Microsoft's documentation on [path length
limits] for possible solutions.

[path length limits]: https://docs.microsoft.com/en-us/windows/desktop/fileio/naming-a-file#maximum-path-length-limitation

### Performance Differences

Our experience shows that builds on Windows are generally slower than they are
on Linux. The cost of `CreateProcess` in comparison to `fork` accounts for much
of the difference, so it is best to minimize process creation in your build
system.

File system performance can also make a large difference. This also appears to
be the reason that Mac, while it has better build performance than Windows,
still underperforms Linux.

Windows and Mac users will see optimum build performance in a Linux VM.
