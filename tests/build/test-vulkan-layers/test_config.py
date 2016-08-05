def match_unsupported(abi, platform, toolchain, subtest=None):
    # Vulkan isn't supported on armeabi
    if abi == 'armeabi':
            return abi

    # Vulkan support wasn't added until android-24
    if platform < 24:
        return platform

    return None
