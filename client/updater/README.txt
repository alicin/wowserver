Keeping your client up to date
==============================

You only ever need to download the big client ONCE. After that, when the server gets new
spell data or fixes, run the updater and it fetches just what changed (usually a few MB).

  Windows : double-click  update-wow.bat
  Linux   : ./update-wow.sh
  macOS   : ./update-wow.sh

Put these files in your WoW folder, next to Wow.exe. If you keep them somewhere else, pass
the path:

  ./update-wow.sh "/home/you/Games/WoW 3.3.5a"
  .\update-wow.ps1 "C:\Games\WoW 3.3.5a"

What it does
  - asks the server what the current patch files are
  - compares them to what you already have (by checksum, not by date)
  - downloads only the ones that differ, verifies the checksum, then swaps them in

What it does NOT touch
  your addons, your interface settings, your keybinds, your realmlist, or anything else.
  It only writes the patch files listed by the server -- today that is Data\patch-Z.MPQ.

If a download is interrupted or corrupt, nothing is applied: the file is only swapped in
after its checksum matches, so you can just run it again.

Server: 167.233.128.19        Portal: https://wow.allahaema.net
