def build_unsupported(abi, platform):
    if abi != 'armeabi-v7a':
        return abi
    return None


def extra_cmake_flags():
    return ['-DANDROID_ARM_NEON=TRUE']
