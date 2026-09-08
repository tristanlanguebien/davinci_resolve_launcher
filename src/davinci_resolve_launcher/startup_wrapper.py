import logging
import os
import json
from davinci_resolve_launcher import TEMP_PROJECT_NAME
from davinci_resolve_launcher.context import get_context, init_context
from importlib import import_module
from typing import Any


def main():
    logging.info("Running Python Startup Wrapper")
    open_startup_project()
    run_startup_function()


def open_startup_project():
    project_name = os.environ.get("STARTUP_PROJECT", "")
    if project_name:
        if project_name == TEMP_PROJECT_NAME:
            create_temp_project()
        logging.info(f"Opening project: {project_name}")
        context = get_context()
        project_manager = context.project_manager
        if project_name not in project_manager.GetProjectListInCurrentFolder():
            logging.warning(f'The project "{project_name}" doest not exist')
            return
        project_manager.LoadProject(project_name)


def create_temp_project():
    context = get_context()
    context.project_manager.DeleteProject(TEMP_PROJECT_NAME)
    context.project_manager.CreateProject(TEMP_PROJECT_NAME)
    context.resolve.OpenPage("edit")


def run_startup_function():
    module = os.environ["STARTUP_MODULE"]
    func = os.environ["STARTUP_FUNCTION"]
    args = json.loads(os.environ["STARTUP_ARGS"])
    kwargs = json.loads(os.environ["STARTUP_KWARGS"])
    if not module or not func:
        return
    logging.info(f"Running startup function: {module}.{func}")
    run_function(module, function=func, args=args, kwargs=kwargs)


def run_function(module: str, function: str, args: list | None = None, kwargs: dict | None = None) -> Any:
    args = args or []
    kwargs = kwargs or {}
    _module = import_module(module)
    _function = getattr(_module, function)
    return _function(*args, **kwargs)


if __name__ == "__main__":
    context = init_context(app, bmd)
    main()
