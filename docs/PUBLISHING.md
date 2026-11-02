# Public repository publication

The intended destination is a **new public `CameraDrone` repository** in the owner's GitHub account. No runtime credentials, recordings or workstation-specific state should be published.

`tools/prepare_public_release.py` creates an allowlisted checkout outside the active workspace, checks it for the actual private runtime token and common GitHub/private-key patterns, and writes a SHA-256 manifest. It includes application source, pinned model weights and license, generated documentation screenshot, tests, CI and the final PDF. It excludes runtime state, inputs, real imagery, upstream sample photographs, logs, caches and build intermediates. Review the resulting manifest before publication.

```bash
python3 tools/prepare_public_release.py /tmp/cameradrone-public
cd /tmp/cameradrone-public
git init -b main
git add .
git commit -m 'Build Camera Studio with offline development, AI and RTP bench'
```

The final prepared checkout may already have a commit; do not recreate it unnecessarily. A local `releases/CameraDrone-public.bundle` can preserve the complete clean commit history without including private working data:

```bash
git clone /path/to/CameraDrone-public.bundle CameraDrone-public
```

Authenticate using your normal GitHub browser/CLI flow. Do not paste credentials into chat or commit them. With an authenticated GitHub CLI, publish the reviewed checkout using:

```bash
gh repo create CameraDrone --public --source . --remote origin --push
```

If the empty public repository was created in the browser instead, add its HTTPS/SSH remote and push `main` normally. Do not force-push over existing content. Check the resulting repository's public visibility, commit, model asset, PDF and Actions result after publication. An attached GitHub connector may support commits to an existing repository while lacking repository-creation capability; a local commit is not proof of a remote push.
