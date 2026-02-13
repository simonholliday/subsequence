# Subsequence Documentation

This folder contains the API documentation build system.

## Building the docs

Install documentation dependencies:
```bash
pip install -e .[docs]
```

Generate HTML documentation:
```bash
./docs/build.sh
```

Output will be in `docs/html/`. Open `docs/html/subsequence.html` in a browser.

## Publishing

The generated HTML can be published to GitHub Pages, Read the Docs, or any static host.
