# GitHub commands

## Verify auth and repo scope

```powershell
gh auth status
git rev-parse --show-toplevel
git status --short
git diff --stat
```

If more than one `gh` account is logged in, confirm the one marked `Active account: true` is `erickson558` (matches this repo's `origin` remote). Switch if needed:

```powershell
gh auth switch --hostname github.com --user erickson558
```

## Stage deliberately

```powershell
git add timermeet_app/ timermeet.py tests/ requirements.txt requirements-dev.txt build_exe.py TimerMeet.exe SDD.md README.md AGENTS.md SECURITY.md .claude/ .gitignore
```

Adjust the file list to what actually changed -- never `git add -A`/`git add .`. Always run `git status --short` again after staging to eyeball what's about to be committed.

## Commit

```powershell
git commit -m "<type>: <summary> (V<version>)"
```

Conventional commit types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`. Use `feat!:`/a `BREAKING CHANGE:` footer for a major version bump (an architecture or platform change).

## Tag and push

```powershell
git tag v<version>
git push origin main
git push origin v<version>
```

## GitHub Release (optionally attaching the compiled exe)

```powershell
gh release create v<version> --title "v<version>" --notes "<summary of what changed>" TimerMeet.exe
```

Omit `TimerMeet.exe` from the command if this release didn't rebuild the binary (don't attach a stale exe).

## Sanity check after publishing

```powershell
gh repo view erickson558/timermeet --json visibility,url,defaultBranchRef
git log --oneline -5
```
