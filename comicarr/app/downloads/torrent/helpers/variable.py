import os


def link(src, dst):
    if os.name == "nt":
        import ctypes

        if ctypes.windll.kernel32.CreateHardLinkW(str(dst), str(src), 0) == 0:
            raise ctypes.WinError()
    else:
        os.link(src, dst)


def symlink(src, dst):
    if os.name == "nt":
        import ctypes

        if ctypes.windll.kernel32.CreateSymbolicLinkW(str(dst), str(src), 1 if os.path.isdir(src) else 0) in [0, 1280]:
            raise ctypes.WinError()
    else:
        os.symlink(src, dst)
