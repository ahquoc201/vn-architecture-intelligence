"""Bundle authored runtime data from its canonical repository location."""

from pathlib import Path
from shutil import copyfile

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithData(build_py):
    def run(self):
        super().run()
        root = Path(__file__).parent
        patterns = (
            "knowledge/architecture/*.json",
            "knowledge/architecture/*.yaml",
            "knowledge/fengshui/*.json",
            "knowledge/fengshui/*.yaml",
            "knowledge/insights.yaml",
            "sources/bibliography.yaml",
        )
        for pattern in patterns:
            for source in sorted(root.glob(pattern)):
                target = Path(self.build_lib) / "vnai" / "_data" / source.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                copyfile(source, target)


setup(cmdclass={"build_py": BuildWithData})
