"""Install the OddJeeves figure check whenever sandboxed code imports matplotlib.

Python imports this module at startup. Patching lazily, when
`matplotlib.figure` is first imported, keeps startup free for code that
never plots.
"""

import importlib.abc
import sys


class _FigureCheckInstaller(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name != "matplotlib.figure":
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(name, path, target)
            if spec is not None and spec.loader is not None:
                break
        else:
            return None
        loader_exec = spec.loader.exec_module

        def exec_module(module):
            loader_exec(module)
            from oddjeeves_figure_check import install

            install(module)

        spec.loader.exec_module = exec_module
        return spec


sys.meta_path.insert(0, _FigureCheckInstaller())
