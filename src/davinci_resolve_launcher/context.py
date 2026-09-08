"""
This module contains a class that is supposed to be initialized once during the execution
of the startup wrapper (app and bmd object cannot be initialized in imported functions, as
they are probably injected to script as module-level objects when executing scripts)

To aleviate this shortcoming, just initialize this object once, so it can be passed across modules and functions
"""


class Context:
    def __init__(self, app, bmd) -> None:
        self.app = app
        self.bmd = bmd

        if self.app is None:
            raise RuntimeError("Failed to initialize App Object")
        if self.bmd is None:
            raise RuntimeError("Failed to initialize Bmd Object")

    @property
    def resolve(self):
        return self.app.GetResolve()

    @property
    def media_storage(self):
        return self.resolve.GetMediaStorage()

    @property
    def project_manager(self):
        return self.resolve.GetProjectManager()

    @property
    def project(self):
        return self.project_manager.GetCurrentProject()

    @property
    def timeline(self):
        return self.project.GetCurrentTimeline()

    @property
    def media_pool(self):
        return self.project.GetMediaPool()

    @property
    def gallery(self):
        return self.project.GetGallery()


CONTEXT: Context | None = None


def init_context(app, bmd) -> Context:
    global CONTEXT
    CONTEXT = Context(app, bmd)
    return CONTEXT


def get_context() -> Context:
    if not CONTEXT:
        raise AttributeError("Context object has not been initialized")
    return CONTEXT
