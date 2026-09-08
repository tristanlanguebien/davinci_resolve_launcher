from pathlib import Path
import os
import shutil
import json
import psutil
import argparse
import time
import sys
import logging
import subprocess
import toml

"""
DaVinci Resolve has a few quirks that make it somewhat complex to have a custom launch process.
Here are the main issues we had to address:

1. By default, Resolve uses the Python installation available on the system,
but its Python environment can be influenced by environment variables.
We need Resolve to use the Python environment from davinci_resolve_launcher virtual environment,
together with the additional packages added using UV.
To achieve this, we use `PYTHONHOME` to point Resolve to the desired Python installation
and `PYTHONPATH` to make the required Python packages available.
Note that `PYTHONHOME` specifies the Python installation/prefix; it does not point directly to `python.exe`.
`PYTHONPATH`, on the other hand, specifies additional locations from which Python can import modules.

2. Resolve does not provide an environment variable to control the location of the project database.
To work around this, we copy a placeholder `Resolve Projects` folder into a custom
directory and modify Resolve's configuration files before launching it.

3. Resolve does not provide an environment variable to configure the location of user scripts.
To work around this, we create a symbolic link in Resolve's default
`Scripts/Utility` directory that points to `conf/resolve/menu_actions`.

4. Resolve does not provide a straightforward mechanism for executing a Python startup script.
However, Resolve/Fusion executes `.scriptlib` files located in the user Scripts directory at startup.
A `.scriptlib` file is a Lua script, which allows us to bootstrap a python script.
The `.scriptlib` file reads the Python wrapper specified by the `PYTHON_STARTUP_WRAPPER` environment variable.

The Python startup wrapper then opens the project specified by `STARTUP_PROJECT`, and executes the function
specified by `STARTUP_MODULE`, `STARTUP_FUNCTION`, and `STARTUP_KWARGS`.

5. Resolve creates global objects such as `app` and `bmd`, but their availability depends on how the script is executed.
In particular, we observed that these globals are available when executing scripts from the Resolve menu or through
the startup mechanism, but are not available from imported Python modules or when using `fuscript.exe`.

To avoid relying on these globals, the Python startup wrapper and all executable scripts use a `Context` object that
stores the relevant Resolve/Fusion objects and passes them explicitly to other modules and functions.
We also observed that some API calls, such as `bmd.scriptapp("Resolve")`, do not work in all execution contexts.
A known limitation of this method is that the Context objects can be recovered when using run_script(),
so only run_function() can be used for arbitrary code execution.

We suspect that some of these limitations comes from using the free version of Resolve,
but we have not been able to verify this against the Studio version.

6. Only one instance of Resolve can run at a time. As a result, scripts need to take special care when starting,
communicating with, or shutting down Resolve to avoid conflicts between multiple processes.

A complete schema of Resolve startup logic can be found here: `./docs/img/resolve_startup_logic.png`

RESOURCES

https://www.youtube.com/watch?v=byrpYDJo_0s
https://www.youtube.com/watch?v=knFyTwAU6BM
https://www.youtube.com/watch?v=ER-XaxRXZMI

Davinci Resolve API Docs
https://extremraym.com/cloud/resolve-scripting-doc/
https://resolvedevdoc.readthedocs.io/en/latest/index.html
https://deric.github.io/DaVinciResolve-API-Docs/

Fusion API Docs
https://documents.blackmagicdesign.com/UserManuals/Fusion8_Scripting_Guide.pdf

https://gitlab.com/WeSuckLess/Reactor

"""

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


ROOT_DIR = Path(__file__).parent
TEMP_PROJECT_NAME = "_temp"


def default_resolve_executable() -> Path:
    return Path("C:/Program Files/Blackmagic Design/DaVinci Resolve/Resolve.exe")


def default_interactive_scripts_dir() -> Path:
    return ROOT_DIR / "resources/interactive_scripts_dir"


def get_environment_variables(
    project: str,
    module: str,
    function: str,
    args: list[str] | None = None,
    kwargs: dict | None = None,
    extra_python_paths: list[Path] | None = None,
) -> dict[str, str]:
    args = args or []
    kwargs = kwargs or {}
    env = {
        "PYTHONHOME": Path(sys._base_executable).parent.as_posix(),  # type: ignore
        "PYTHONPATH": ";".join([path.as_posix() for path in get_python_paths(extra_python_paths)]),
        "PYTHON_STARTUP_WRAPPER": (ROOT_DIR / "startup_wrapper.py").as_posix(),
        "RESOLVE_SCRIPT_API": resolve_script_api().as_posix(),  # Not used for now, but may be useful in the Studio edition of Resolve
        "RESOLVE_SCRIPT_LIB": resolve_script_lib().as_posix(),  # Not used for now, but may be useful in the Studio edition of Resolve
    }

    # Project
    env["STARTUP_PROJECT"] = project

    # Startup function
    env["STARTUP_MODULE"] = module
    env["STARTUP_FUNCTION"] = function
    env["STARTUP_ARGS"] = json.dumps(args)
    env["STARTUP_KWARGS"] = json.dumps(kwargs)
    return env


def parse_config_file(config_file: Path):
    conf = toml.load(config_file)
    return conf


def open(
    resolve_executable: Path | None = None,
    interactive_scripts_dir: Path | None = None,
    kill: bool = False,
    project_name: str = "",
    project_database: Path | None = None,
    module: str = "",
    function: str = "",
    args: list[str] | None = None,
    kwargs: dict | None = None,
    extra_python_paths: list[Path] | None = None,
):
    # Executable
    resolve_executable = Path(resolve_executable) if resolve_executable else default_resolve_executable()
    if not resolve_executable.exists():
        raise FileNotFoundError(f"Executable to DaVinci Resolve not found: {resolve_executable}")

    # Interactive scripts dir
    interactive_scripts_dir = (
        Path(interactive_scripts_dir) if interactive_scripts_dir else default_interactive_scripts_dir()
    )
    if not interactive_scripts_dir.exists():
        raise FileNotFoundError(f"Executable to DaVinci Resolve not found: {interactive_scripts_dir}")

    check_existing_processes(kill=kill)
    configure_interactive_scripts_dir(interactive_scripts_dir)
    setup_startup_wrapper()
    setup_project_database(project_database)
    command = [resolve_executable.as_posix()]

    env = os.environ.copy()
    env.update(
        get_environment_variables(
            project=project_name,
            module=module,
            function=function,
            args=args,
            kwargs=kwargs,
            extra_python_paths=extra_python_paths,
        )
    )
    subprocess.Popen(command, env=env)


def check_existing_processes(kill: bool = False):
    logging.info("Checking existing processes")
    for process in psutil.process_iter():
        if process.name() == "Resolve.exe":
            if kill:
                logging.warning("Killing DaVinci Resolve instance")
                process.kill()
                time.sleep(0.1)
            else:
                raise RuntimeError("Another instance of Davinci Resolve is already running")


def is_junction(path: Path) -> bool:
    try:
        return bool(os.readlink(path))
    except OSError:
        return False


def configure_interactive_scripts_dir(scripts_dir: Path):
    """Creates a symbolic link to the interactive scripts dir"""
    logging.info(f"Configuring interactive scripts ({scripts_dir})")
    dst = user_scripts_path()

    if dst.exists():
        if not is_junction(dst):
            logging.info(f"Archiving current interactive scripts dir ({dst})")
            shutil.move(dst, dst.with_name("__" + dst.name))
        else:
            dst.unlink(missing_ok=True)

    command = [
        "powershell.exe",
        "-Command",
        f'New-Item -ItemType Junction -Path "{dst}" -Target "{scripts_dir}"',
    ]
    subprocess.run(command, check=True)


def src_startup_wrapper() -> Path:
    return ROOT_DIR / "resources/lua_startup_wrapper.scriptlib"


def dst_startup_wrapper() -> Path:
    return user_scripts_path() / "Utility" / src_startup_wrapper().name


def setup_startup_wrapper():
    src = src_startup_wrapper()
    dst = dst_startup_wrapper()
    logging.info(f"Setting up LUA startup wrapper ({dst})")
    shutil.copy(src, dst)


def get_python_paths(extra_python_paths: list[Path] | None = None) -> list[Path]:
    paths = [
        Path(sys.executable).parent.parent / "Lib/site-packages",
        modules_path(),  # Not used for now, but may be useful in the Studio edition of Resolve
    ]
    extra_python_paths = extra_python_paths or []
    for path in extra_python_paths:
        paths.append(Path(path))

    # In editable mode, add the src folder to PYTHONPATH
    parent = Path(__file__).parent.parent
    if parent.name == "src":
        paths.append(parent)
    return paths


def resolve_script_api() -> Path:
    """
    This environment variable is needed to use DaVinciResolveScript.py from extrerna scripts
    Not used at the moment, as it probably only works in the Studio Edition of Resolve
    """
    program_data = Path(os.environ["PROGRAMDATA"])
    resolve_script_api = program_data / "Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting"
    return resolve_script_api


def resolve_script_lib() -> Path:
    """
    This environment variable is needed to use DaVinciResolveScript.py from extrerna scripts
    Not used at the moment, as it probably only works in the Studio Edition of Resolve
    """
    return Path("C:/Program Files/Blackmagic Design/DaVinci Resolve/fusionscript.dll")


def modules_path() -> Path:
    """
    This environment variable is needed to use DaVinciResolveScript.py from extrerna scripts
    Not used at the moment, as it probably only works in the Studio Edition of Resolve
    (should be added to PYTHONPATH)
    """
    return resolve_script_api() / "Modules"


def user_scripts_path() -> Path:
    """Path where interactive scripts should be placed"""
    return Path(
        f"C:/Users/{os.environ['USERNAME']}/AppData/Roaming/Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts"
    )


def programdata_scripts_path() -> Path:
    """Path where scripts should be placed"""
    return Path("C:/ProgramData/Blackmagic Design/DaVinci Resolve/Fusion/Scripts")


def setup_project_database(project_database: Path | None = None):
    if not project_database:
        return
    project_database = Path(project_database)
    logging.info(f"Setup project database ({project_database})")
    db_name = project_database.name
    db_path = project_database / "Resolve Project Library"

    # Copy default empty project database at the right place
    if not db_path.exists():
        db_path.mkdir(exist_ok=True, parents=True)
        projects_template = Path(__file__).parent / "resources/Resolve Projects"
        dst = db_path / projects_template.name
        shutil.copytree(projects_template, dst)

    # Add the database to the db list config
    db_list = Path(
        f"C:/Users/{os.environ['USERNAME']}/AppData/Roaming/Blackmagic Design/DaVinci Resolve/Preferences/dblist.conf"
    )
    content = db_list.read_text()
    if f"{db_name}:" not in content:
        content = content.strip()
        content += f"\n{db_name}:{str(db_path).replace(':', '')}:*:::DISK\n"
        db_list.write_text(content)

    # Set active db
    active_db = Path(
        f"C:/Users/{os.environ['USERNAME']}/AppData/Roaming/Blackmagic Design/DaVinci Resolve/Preferences/activedb.conf"
    )
    active_db.write_text(f"disk*:{db_name}\n")


def clear():
    logging.info("Clearing DaVinci Resolve Launcher setup")
    path = user_scripts_path()
    if is_junction(path):
        logging.info("Clearing interactive scripts dir")
        path.unlink()
    src = path.parent / "__Scripts"
    if src.exists():
        logging.info("Restoring default interactive scripts dir")
        shutil.move(src, path)


def parse_arguments():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-o", "--open", action="store_true", help="Open action")
    group.add_argument("-c", "--clear", action="store_true", help="Clear action")
    parser.add_argument(
        "-p",
        "--project",
        type=str,
        required=False,
        default="",
        help="Name of the project to open at launch."
        ' The value "_temp" can be set to create an empty project'
        ' (WARNING: if not manually saved, the "_temp" project is automatically deleted at each launch)',
    )
    parser.add_argument("-e", "--executable", type=Path, required=False, help="Path to Davinci Resolve executable")
    parser.add_argument(
        "-isd",
        "--interactive_scripts_dir",
        type=Path,
        required=False,
        help="Path to the directory where scripts are located",
    )
    parser.add_argument("-k", "--kill", action="store_true")
    parser.add_argument(
        "-pdb", "--project_database", required=False, type=Path, help="Path to a custom project database"
    )
    group = parser.add_argument_group()
    group.add_argument("-m", "--module", type=str, required=False, help="module to import")
    group.add_argument("-f", "--function", type=str, required=False, help="function to run")
    group.add_argument("-a", "--args", nargs="+", help="arguments to pass to the function")
    group.add_argument(
        "-kw",
        "--kwargs",
        type=str,
        help="kwargs to pass to the function, written at the format key1=value1;key2=value2\nWarning: all kwargs will be considered as strings, make sure to convert them",
    )
    group.add_argument(
        "-epp",
        "--extra_python_paths",
        nargs="+",
        type=Path,
        help="Extra paths to packages/modules to add to PYTHONPATH",
    )

    args = parser.parse_args()

    # format kwargs
    kwargs = {}
    if args.kwargs:
        for kwarg_str in args.kwargs.split(";"):
            key, value = kwarg_str.split("=")
            kwargs[key.strip()] = value.strip()

    if args.open:
        open(
            resolve_executable=args.executable,
            interactive_scripts_dir=args.interactive_scripts_dir,
            kill=args.kill,
            project_name=args.project,
            project_database=args.project_database,
            module=args.module,
            function=args.function,
            args=args.args,
            kwargs=kwargs,
            extra_python_paths=args.extra_python_paths,
        )
        return

    if args.clear:
        clear()


if __name__ == "__main__":
    logging.info("Hello world")
    parse_arguments()
