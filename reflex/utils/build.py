"""Building the app and initializing all prerequisites."""

from __future__ import annotations

import json
import os
import random
import subprocess
import zipfile
from enum import Enum
from pathlib import Path
from typing import Optional, Union

from rich.progress import MofNCompleteColumn, Progress, TimeElapsedColumn

from reflex import constants
from reflex.config import get_config
from reflex.utils import console, path_ops, prerequisites, processes


def update_json_file(file_path: str, update_dict: dict[str, Union[int, str]]):
    """Update the contents of a json file.

    Args:
        file_path: the path to the JSON file.
        update_dict: object to update json.
    """
    fp = Path(file_path)
    # create file if it doesn't exist
    fp.touch(exist_ok=True)
    # create an empty json object if file is empty
    fp.write_text("{}") if fp.stat().st_size == 0 else None

    with open(fp) as f:  # type: ignore
        json_object: dict = json.load(f)
        json_object.update(update_dict)
    with open(fp, "w") as f:
        json.dump(json_object, f, ensure_ascii=False)


def set_reflex_project_hash():
    """Write the hash of the Reflex project to a REFLEX_JSON."""
    project_hash = random.getrandbits(128)
    console.debug(f"Setting project hash to {project_hash}.")
    update_json_file(constants.REFLEX_JSON, {"project_hash": project_hash})


def set_env_json():
    """Write the upload url to a REFLEX_JSON."""
    update_json_file(
        constants.ENV_JSON,
        {
            "uploadUrl": constants.Endpoint.UPLOAD.get_url(),
            "eventUrl": constants.Endpoint.EVENT.get_url(),
            "pingUrl": constants.Endpoint.PING.get_url(),
        },
    )


def set_os_env(**kwargs):
    """Set os environment variables.

    Args:
        kwargs: env key word args.
    """
    for key, value in kwargs.items():
        if not value:
            continue
        os.environ[key.upper()] = value


def generate_sitemap_config(deploy_url: str):
    """Generate the sitemap config file.

    Args:
        deploy_url: The URL of the deployed app.
    """
    # Import here to avoid circular imports.
    from reflex.compiler import templates

    config = json.dumps(
        {
            "siteUrl": deploy_url,
            "generateRobotsTxt": True,
        }
    )

    with open(constants.SITEMAP_CONFIG_FILE, "w") as f:
        f.write(templates.SITEMAP_CONFIG(config=config))


class _ComponentName(Enum):
    BACKEND = "Backend"
    FRONTEND = "Frontend"


def _zip(
    component_name: _ComponentName,
    target: str,
    root_dir: str,
    dirs_to_exclude: set[str] | None = None,
    files_to_exclude: set[str] | None = None,
) -> None:
    """Zip utility function.

    Args:
        component_name: The name of the component: backend or frontend.
        target: The target zip file.
        root_dir: The root directory to zip.
        dirs_to_exclude: The directories to exclude.
        files_to_exclude: The files to exclude.

    """
    dirs_to_exclude = dirs_to_exclude or set()
    files_to_exclude = files_to_exclude or set()
    files_to_zip: list[str] = []
    # Traverse the root directory in a top-down manner. In this traversal order,
    # we can modify the dirs list in-place to remove directories we don't want to include.
    for root, dirs, files in os.walk(root_dir, topdown=True):
        # Modify the dirs in-place so excluded and hidden directories are skipped in next traversal.
        dirs[:] = [
            d
            for d in dirs
            if (basename := os.path.basename(os.path.normpath(d)))
            not in dirs_to_exclude
            and not basename.startswith(".")
        ]
        # Modify the files in-place so the hidden files are excluded.
        files[:] = [f for f in files if not f.startswith(".")]
        files_to_zip += [
            os.path.join(root, file) for file in files if file not in files_to_exclude
        ]

    # Create a progress bar for zipping the component.
    progress = Progress(
        *Progress.get_default_columns()[:-1],
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )
    task = progress.add_task(
        f"Zipping {component_name.value}:", total=len(files_to_zip)
    )

    with progress, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file in files_to_zip:
            console.debug(f"{target}: {file}")
            progress.advance(task)
            zipf.write(file, os.path.relpath(file, root_dir))


def export(
    backend: bool = True,
    frontend: bool = True,
    zip: bool = False,
    deploy_url: Optional[str] = None,
):
    """Export the app for deployment.

    Args:
        backend: Whether to zip up the backend app.
        frontend: Whether to zip up the frontend app.
        zip: Whether to zip the app.
        deploy_url: The URL of the deployed app.
    """
    # Remove the static folder.
    path_ops.rm(constants.WEB_STATIC_DIR)

    # The export command to run.
    command = "export"

    if frontend:
        # Generate a sitemap if a deploy URL is provided.
        if deploy_url is not None:
            generate_sitemap_config(deploy_url)
            command = "export-sitemap"

        checkpoints = [
            "Linting and checking ",
            "Compiled successfully",
            "Route (pages)",
            "Collecting page data",
            "automatically rendered as static HTML",
            'Copying "static build" directory',
            'Copying "public" directory',
            "Finalizing page optimization",
            "Export successful",
        ]
        # Start the subprocess with the progress bar.
        process = processes.new_process(
            [prerequisites.get_package_manager(), "run", command],
            cwd=constants.WEB_DIR,
            shell=constants.IS_WINDOWS,
        )
        processes.show_progress("Creating Production Build", process, checkpoints)

    # Zip up the app.
    if zip:
        files_to_exclude = {constants.FRONTEND_ZIP, constants.BACKEND_ZIP}
        if frontend:
            _zip(
                component_name=_ComponentName.FRONTEND,
                target=constants.FRONTEND_ZIP,
                root_dir=".web/_static",
                files_to_exclude=files_to_exclude,
            )
        if backend:
            _zip(
                component_name=_ComponentName.BACKEND,
                target=constants.BACKEND_ZIP,
                root_dir=".",
                dirs_to_exclude={"assets", "__pycache__"},
                files_to_exclude=files_to_exclude,
            )


def setup_frontend(
    root: Path,
    disable_telemetry: bool = True,
):
    """Set up the frontend to run the app.

    Args:
        root: The root path of the project.
        disable_telemetry: Whether to disable the Next telemetry.
    """
    # Install frontend packages.
    prerequisites.install_frontend_packages()

    # Copy asset files to public folder.
    path_ops.cp(
        src=str(root / constants.APP_ASSETS_DIR),
        dest=str(root / constants.WEB_ASSETS_DIR),
    )

    # Set the environment variables in client (env.json).
    set_env_json()

    # Disable the Next telemetry.
    if disable_telemetry:
        processes.new_process(
            [
                prerequisites.get_package_manager(),
                "run",
                "next",
                "telemetry",
                "disable",
            ],
            cwd=constants.WEB_DIR,
            stdout=subprocess.DEVNULL,
            shell=constants.IS_WINDOWS,
        )


def setup_frontend_prod(
    root: Path,
    disable_telemetry: bool = True,
):
    """Set up the frontend for prod mode.

    Args:
        root: The root path of the project.
        disable_telemetry: Whether to disable the Next telemetry.
    """
    setup_frontend(root, disable_telemetry)
    export(deploy_url=get_config().deploy_url)
