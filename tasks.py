import os

from invoke import task
from invoke.context import Context


DIRNAME = os.path.dirname(__file__)


@task
def format_check(ctx: Context) -> None:
    cmd = "ruff format --check"
    print(cmd)
    ctx.run(cmd)


@task
def mypy(ctx: Context) -> None:
    src = os.path.join(DIRNAME, "subsequence")
    cmd = f"mypy {src}"
    print(cmd)
    ctx.run(cmd)


@task
def pytest(ctx: Context) -> None:
    cmd = "python -m pytest tests/ -q"
    print(cmd)
    ctx.run(cmd)


@task(format_check, mypy, pytest, default=True)
def build(_):
    pass
