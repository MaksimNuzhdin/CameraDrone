# Public repository publication

The public repository is [MaksimNuzhdin/CameraDrone](https://github.com/MaksimNuzhdin/CameraDrone). Publish updates to its existing history. No runtime credentials, recordings or workstation-specific state should be published.

`tools/prepare_public_release.py` creates an allowlisted checkout outside the active workspace, checks it for the actual private runtime token and common GitHub/private-key patterns, and writes a SHA-256 manifest. It includes application source, pinned model weights and license, generated documentation screenshot, tests, CI and the final PDF. It excludes runtime state, inputs, real imagery, upstream sample photographs, logs, caches and build intermediates. Review the resulting manifest before publication.

```bash
python3 tools/prepare_public_release.py /tmp/cameradrone-public
```

Review and copy the prepared files into an authenticated existing checkout, preserving `.git`. Verify `git diff --check`, inspect the diff, commit and push `main`. Do not initialize a second unrelated history for an existing repository.

The final prepared checkout may already have a commit; do not recreate it unnecessarily. A local `releases/CameraDrone-public.bundle` can preserve the complete clean commit history without including private working data:

```bash
git clone /path/to/CameraDrone-public.bundle CameraDrone-public
```

Authenticate using the owner's normal GitHub browser/SSH/CLI flow. Never commit credentials. With an existing checkout:

```bash
git diff --check
git add .
git commit -m 'Add validated Pi camera RTP and installation tooling'
git push origin main
git bundle create /path/to/CameraDrone-public.bundle --all
```

Do not force-push over existing content. Check the resulting repository's public visibility, commit, model asset, PDF and Actions result after publication. A local commit or bundle is not proof of a remote push. Build the optional deterministic software archive with `tools/build_release.py` after generating the final PDF; the archive itself is a local release artifact, not committed recursively into its own contents.
