# GitHub Commands

## Verify Auth

```powershell
gh auth status
gh auth status -h github.com
```

Do not store the token in project files. Use the existing authenticated account from `gh`.

## Detect Repo Scope

```powershell
git rev-parse --show-toplevel
git status --short
git diff --stat
```

If the root is `.../www`, decide explicitly whether you are publishing the whole monorepo or only `monitoreos/timermeet`.

## Safer Standalone Publish for TimerMeet Only

When `timermeet` must become its own public repository, prefer exporting it to a clean folder first instead of pushing the whole `www` tree.

```powershell
$source = 'C:\Program Files (x86)\EasyPHP-Webserver-14.1b2\www\monitoreos\timermeet'
$target = "$env:TEMP\timermeet-github-export"
Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $target | Out-Null
robocopy $source $target /E
Set-Location $target
git init -b main
git add .
git commit -m "feat: initialize TimerMeet EasyPHP project"
gh repo create timermeet --public --source . --remote origin --push
```

## Commit Inside Existing Repo

Use this only if the user explicitly wants to keep `timermeet` inside the existing repo history.

```powershell
git add monitoreos/timermeet
git commit -m "feat(timermeet): update local meeting timers"
git push origin main
```

## Tag and Release

```powershell
git tag v1.1.0
git push origin v1.1.0
gh release create v1.1.0 --title "v1.1.0" --notes "TimerMeet release"
```
