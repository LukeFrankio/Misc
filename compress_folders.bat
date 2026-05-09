@echo off
for /d %%X in (*) do "C:\Program Files\7-Zip\7z.exe" a "%%X.7z" "%%X\"
pause