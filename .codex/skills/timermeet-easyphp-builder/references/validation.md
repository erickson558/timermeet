# Validation Commands

## Locate PHP

Use the installed EasyPHP binary first:

```powershell
$php = 'C:\Program Files (x86)\EasyPHP-Webserver-14.1b2\binaries\php\php.exe'
```

If the path changes, locate it:

```powershell
Get-ChildItem 'C:\Program Files (x86)\EasyPHP-Webserver-14.1b2' -Recurse -Filter php.exe
```

## Syntax Checks

```powershell
& $php -l index.php
& $php -l api\meetings.php
node --check assets\app.js
```

## Local HTTP Check

Start a temporary server:

```powershell
$proc = Start-Process -WindowStyle Hidden -FilePath $php -ArgumentList '-S','127.0.0.1:8124' -WorkingDirectory (Get-Location) -PassThru
```

Check the site and API:

```powershell
Invoke-WebRequest 'http://127.0.0.1:8124/' -UseBasicParsing | Select-Object -ExpandProperty StatusCode
Invoke-WebRequest 'http://127.0.0.1:8124/api/meetings.php' -UseBasicParsing | Select-Object -ExpandProperty Content
```

Stop the temporary server:

```powershell
Stop-Process -Id $proc.Id
```
