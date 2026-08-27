"""Project entrypoint. Just delegates to the Typer app in `jobfinder.cli`."""

from jobfinder.cli import main

if __name__ == "__main__":
    main()
