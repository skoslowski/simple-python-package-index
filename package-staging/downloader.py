import shutil
import subprocess
import sys
from argparse import ArgumentParser
from pathlib import Path

PIP = [sys.executable, "-m", "pip", "--disable-pip-version-check"]

package_platform_override = {
    # pin the platform tag for a certain package and OS
    # "linux": {"numpy": "manylinux1_x86_64"}
}


def load_requirements(requirements_file: Path) -> list[str]:
    requirements = []
    content = requirements_file.read_text(encoding="utf-8")
    requirements = (
        line.split("#")[0].split(";")[0].strip() for line in content.splitlines()
    )  # remove comments
    requirements = [p for p in requirements if p]  # remove empty entries

    print(f"Found {len(content)} requirements in {requirements_file}")
    return requirements


def download_packages(python_version: tuple[int, int], requirements: list[str], dest: Path):
    print("Downloading packages")
    shutil.rmtree(dest, ignore_errors=True)

    pip_download_args_common = [
        f"--dest={dest}",
        "--no-deps",  # already taken care of pip-compile
        "--implementation=cp",
        f"--python-version={python_version[0]}{python_version[1]}",
        f"--abi=cp{python_version[0]}{python_version[1]}",
    ]

    os_platforms = [
        [
            "linux",
            [
                "manylinux_2_17_x86_64",
                "manylinux2014_x86_64",
                "manylinux_2_12_x86_64",
                "manylinux2010_x86_64",
                "manylinux_2_5_x86_64",
                "manylinux1_x86_64",
            ],
        ],
        ["windows", ["win_amd64"]],
    ]

    for os_name, platforms in os_platforms:
        print(f"Downloading for platform {os_name}")

        special_cases = package_platform_override.get(os_name, {})
        for platforms_requirements in split_special_cases(requirements, platforms, special_cases):
            subprocess.run(
                [
                    *PIP,
                    "download",
                    *pip_download_args_common,
                    *platforms_requirements,
                ],
                check=True,
            )


def create_universal_wheels(dest: Path):
    sdists = list(dest.glob("*.tar.gz"))
    print(f"Found {len(sdists)} sdists")

    pip_wheel = [*PIP, "wheel", "--no-deps", "--wheel-dir=wheels"]
    for sdist in sdists:
        print("Building wheel for", sdist)
        result = subprocess.run(
            [*pip_wheel, str(sdist)],
            check=True,
            capture_output=True,
        )
        output = result.stdout.decode()
        if "none-any.whl" not in output:
            print(output)
            raise ValueError("not a universal wheel")
        sdist.unlink()


def split_special_cases(requirements: list, default_platforms: list, overrides: dict):
    for package_name, platform in overrides.items():
        requirement = next((r for r in requirements if r.startswith(package_name)), None)
        requirements.remove(requirement)
        assert platform in default_platforms
        yield [f"--platform={platform}", requirement]
    if requirements:
        yield [*[f"--platform={p}" for p in default_platforms], *requirements]


def main():
    parser = ArgumentParser()

    def parse_version(value: str) -> tuple[int, int]:
        parts = value.split(".")
        return int(parts[0]), int(parts[1])

    parser.add_argument("--python", type=parse_version, default=sys.version_info[:2])
    parser.add_argument("--dest", type=Path, default=Path("wheels"))
    parser.add_argument("requirements", type=Path)

    args = parser.parse_args()

    print(f"Downloading for CPython {args.python[0]}.{args.python[1]}")

    requirements = load_requirements(args.requirements)

    download_packages(args.python, requirements, args.dest)

    create_universal_wheels(args.dest)


if __name__ == "__main__":
    main()
