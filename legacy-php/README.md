# TimerMeet — legacy PHP baseline (frozen at v1.3.0)

This folder holds the original EasyPHP + vanilla JS implementation of TimerMeet, kept
for reference and rollback after the project moved to a native Python desktop app in
`v2.0.0` (see the repository root `README.md` and `SDD.md`).

## Why it moved here

The PHP/JS version's reminders only fire while a browser tab stays open and focused,
which was the main reliability complaint that triggered the Python rewrite. This code
is not actively maintained anymore, but it is fully preserved (same files, same git
history) in case the PHP version is ever needed again.

## Running it again (if needed)

The code is untouched from `v1.3.0`, so `api/meetings.php` still resolves its storage
path as `dirname(__DIR__) . '/data'`, which now points at `legacy-php/data` instead of
the repository root `data/` used by the current Python app. To run this legacy version
again:

1. Copy or symlink the repository's `data/meetings.json` into `legacy-php/data/meetings.json`
   (or point your EasyPHP/Apache document root so that `legacy-php/` itself is the site
   root, in which case `dirname(__DIR__)/data` should be created next to `index.php` as
   before).
2. Serve `legacy-php/` with `EasyPHP-Webserver-14.1b2` (or Apache + PHP >= 5.4) exactly
   as described in the historical usage notes.

No code in this folder is modified going forward; new features and fixes only happen
in the Python app at the repository root.
