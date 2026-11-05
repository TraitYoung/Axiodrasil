# Current Project Definition

Axiodrasil is a virtual embodiment experiment focused exclusively on Bina. The eventual goal is camera access with user authorization, visual perception, and interaction grounded in Bina's virtual presence and memory.

Bina is the only active character. All other characters are documentation-only historical settings in `docs/characters/`. Do not restore multi-agent routing, cabinet group chat, other character runtimes, or the general development pipeline as part of routine work.

Current development priorities are Bina's virtual embodiment, interaction, and memory systems. Camera capture and visual understanding are planned capabilities, not implemented features. README.md and TODO.md define the current scope. Older BIOS and cabinet documents are historical references.

Long-term memory is provided exclusively by Hindsight. Local SQLite stores raw chat history and mood state. Do not reintroduce the retired L3/FTS/vector, cabinet, Redis or rolling-summary memory implementations.

# Repository Guidelines

## Project Structure & Module Organization

The workspace contains a FastAPI backend (`main.py`, `agents/`, `modules/`, `memory/`, `storage/`) and a Next.js frontend (`frontend/`). The `.git/`, `.agents/`, `.codex/`, and `.aws/` directories are reserved for repository or environment metadata; do not place application code there.

When adding the first implementation, organize code by responsibility and document the layout in `README.md`. Use clearly named directories such as `src/` for application code, `tests/` for tests, and `assets/` for static resources when those categories apply.

## Build, Test, and Development Commands

Development and check commands are documented in README.md. Python dependencies are in requirements.txt and frontend commands are in frontend/package.json.

When introducing a toolchain, provide its dependency manifest and document exact installation, development, build, and test commands in `README.md`. Prefer a small set of reproducible commands over undocumented local setup steps.

## Coding Style & Naming Conventions

Follow the standard conventions of the language selected for the project. Use consistent indentation, descriptive names, and small modules with focused responsibilities. Configure the language's formatter and linter alongside the first source files, and document how to run them.

Keep changes scoped to the requested behavior. Avoid speculative abstractions, redundant validation, and unrelated formatting changes.

## Testing Guidelines

No testing framework or coverage threshold is established. Add tests for meaningful behavior as functionality is introduced. Use descriptive test names that identify the behavior being verified, and follow the selected framework's file naming conventions. Document the test command and any required fixtures or setup.

## Commit & Pull Request Guidelines

Use the existing Git history for development context. Use concise, imperative commit subjects, such as `Add initial application structure`.

Pull requests should describe the problem, the resulting behavior, and validation performed. Link relevant issues and include screenshots for visible UI changes. Explicitly identify any checks that could not be run.

## Security & Configuration

Keep credentials, tokens, and private configuration out of source files and commits. Document required configuration using placeholder values, and exclude local secret files through `.gitignore` when configuration is introduced.
