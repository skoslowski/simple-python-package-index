from pathlib import Path
from subprocess import run

data_dir = Path(__file__).parent


run(["pip", "download", "sh"], cwd=data_dir)

base = data_dir / "base"
base.mkdir(exist_ok=True)
run(["pip", "download", "pytest"], cwd=base)

ext = data_dir / "ext"
ext.mkdir(exist_ok=True)
run(["pip", "download", "bitarray"], cwd=ext)
