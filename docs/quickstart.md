# Quick Start

## Installation

=== "uv"
    ```
    uv add davinci_resolve_launcher
    ```

=== "pip"
    ```
    pip install davinci_resolve_launcher
    ```

## Writing A Configuration File

Each Resolve configuration is driven by a toml file, that will be fed to the launcher's entry point.

Here are all settings that can be configured (if some of them are not relevant to you, just remove or comment out the lines):

=== "my_config.toml"
```toml
# Specify the path to DaVinci Resolve executable
# default: "C:/Program Files/Blackmagic Design/DaVinci Resolve/Resolve.exe"
resolve_executable = "C:/Program Files/Blackmagic Design/DaVinci Resolve/Resolve.exe"

# Specify path to the scripts dir
interactive_scripts_dir = "D:/my_custom_script_dir"

# Set to true to kill any existing instance of Resolve
# default: false
kill = true

# Project database to load (if it does not exist, a new project database will be created)
project_database = "D:/my_custom_project_db"

# Project to open on startup
project_name = "my project"

# Function to execute at startup
module = "my_module"
function = "my_function"
args = ["hello", "world"]
kwargs.kwarg1 = "HELLO"
kwargs.kwarg2 = "WORLD"

# Additional paths from which you may import modules/packages.
extra_python_paths= [
    "D:/my_custom_modules"
]
```








---

!!! info ""
    <a href="Next Section"> <div style="text-align: right; font-weight: bold"> [Next Section : Quick Start](./quickstart.md) </div>