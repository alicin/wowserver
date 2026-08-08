# mod-item-browser

A GM item browser for the 3.3.5a client: search 46,098 items by name or id, see them with
their real icons and colours, hover for a real tooltip, and hand one to whoever you have
selected.

    /ib                 toggle the window
    /ib <text>          open and search
    /ib status          which database and which command transport is in use
    /ib chat | addon    force a command transport (escape hatch, see below)

```
client/addons/mod-item-browser/
  ItemBrowser/            <- the AddOns folder, installed verbatim as AddOns/ItemBrowser
    ItemBrowser.toc
    Data.lua                storage shape and accessors        hand-written
    Search.lua              query -> ranked row indices        hand-written
    Transport.lua           issuing the GM command             hand-written
    UI.xml / UI.lua         window, rows, tooltips, giving     hand-written
    Data/                   GENERATED -- never hand-edit
  tools/
    itemdb.py               the generator (read-only DB access)
    regen.sh                one command: emit, then re-verify
```

## The three decisions worth knowing

### 1. It gives items with `.additem <name> <id> <count>`

An addon cannot create an item; it can only ask the server to. `.additem` already targets the
selection, and falls back to the caster:

```
.work/ac-src/src/server/scripts/Commands/cs_misc.cpp:1741-1742
    if (!player)
        player = PlayerIdentifier::FromTargetOrSelf(handler);

.work/ac-src/src/server/game/Chat/ChatCommands/ChatCommandTags.cpp:141
    if (Player* target = player->GetSelectedPlayer())   return { *target };
```

So no special "give to target" command is needed, and `.send items` (cs_send.cpp:40) is the
wrong tool — it mails the item rather than putting it in the bags.

The recipient name is nonetheless **always** sent explicitly. The first parameter is
`Optional<PlayerIdentifier>`, and the optional-argument parser is greedy with backtracking
(`ChatCommand.h:72-99`): it first tries to eat the next token as a player, and
`PlayerIdentifier::TryConsume` accepts a bare number as a character *low GUID*
(`ChatCommandTags.cpp:92-99`). `.additem 2589 20`
is therefore first attempted as "give item 20 to the character with guid 2589", and only
reparses correctly because item 20 does not exist. That is a lookup failure saving us, not a
design. A name can only parse one way, so a name is what gets sent.

The command travels over AzerothCore's addon-message command channel
(`Chat.cpp:1063`, dispatched from `ChatHandler.cpp:302`), which returns a machine-readable
ack / ok / fail so the window can say "the server refused that" instead of leaving you to read
chat. The addon pings that channel once at login; if nothing answers within five seconds it
falls back to `SendChatMessage(".additem ...", "SAY")`, which works everywhere but has no
reply channel. **A failed command is never retried on the other transport** — a lost
acknowledgement is annoying, two Shadowmournes is worse.

### 2. The item data is shipped, not asked for

A 3.3.5a client only knows items already in its `itemcache.wdb`, so `GetItemInfo` returns nil
for essentially everything on a fresh install and a naive browser shows blank rows. `tools/itemdb.py`
bakes `acore_world.item_template` into Lua. Icons are not in `item_template`: they come from
`displayid -> ItemDisplayInfo.dbc` field 5, `inventoryIcon[0]`, read from `/srv/wow/data/dbc`.

Measured on 2026-08-08: **46,098 items, 4,851 distinct icons, 2.22 MB across 11 files**, the
largest 299 KB. Sharded at 6,000 rows per file. For scale, the pinned addon set already ships
a single 5.1 MB Lua file (`Questie-335/Database/Wotlk/wotlkNpcDB.lua`), so this is comfortably
inside what this client loads — the shard budget exists to make "the database grew 10x" fail
in the generator rather than in game.

Two icon quirks in this client's data, both found with `--icon-check` and both load-bearing:

* one display carries `INV_Chest_Fur.tga`; the archive holds `INV_Chest_Fur.blp` and nothing
  called `INV_Chest_Fur.tga.blp`, so the extension is stripped;
* three carry a **trailing space** (`"INV_Misc_Food_93_SkethylBerries "`) and the `.blp`
  inside `locale-enUS.MPQ` has the space in its filename too. Trimming breaks those icons.

Five icon names in the whole table resolve to no file at all, on six items, all of them
internal junk (`Monster - Item, Glass - Clear`, `NPC Equip 6128`, deprecated rows). The row
template keeps a question mark texture in the layer behind the icon, so those draw as a
question mark rather than as a hole.

### 3. Tooltips are real tooltips, eventually

Only the client can draw a true item tooltip, and only from data the server sends it. Touching
`GetItemInfo(id)` for an unknown item returns nil *and* queues the query. So hovering a row
does both halves: it draws a summary from the shipped database immediately (name, quality,
item level, required level, slot, class, item id), then keeps checking `GetItemInfo` for six
seconds and swaps in `GameTooltip:SetHyperlink(link)` — the genuine tooltip, with stats and
flavour text — the moment the server answers. The first hover of an item flickers; every
hover after that is instant.

## Regenerating

```sh
client/addons/mod-item-browser/tools/regen.sh              # emit, then re-verify
client/addons/mod-item-browser/tools/regen.sh --icon-check # also probe the client MPQs (~25s)
scripts/client-addons.sh                                   # install into the working client
```

`regen.sh` emits and then runs `itemdb.py --check`, which re-derives everything from the DB
and byte-compares it against what is now on disk. Output is deterministic — no timestamps,
input ordered by entry — so a re-run against an unchanged `item_template` rewrites the same
bytes and `--check` is a plain byte comparison. Ten generator invariants are hard failures in
both directions; see the module docstring in `tools/itemdb.py`.

The generator reads the world DB through the same read-only `docker compose exec mysql`
path the rest of this repo uses, and writes only into `ItemBrowser/Data/`.

## Installation wiring

Registered in `client/addons.txt` as

```
client/addons/mod-item-browser/ItemBrowser    -    local:ItemBrowser    -
```

`local:NAME` is a new mode added to `scripts/client-addons.sh` for addons written in this repo
rather than fetched from GitHub: field 1 is a repo-relative directory, nothing is downloaded,
and there is no SHA to pin because this repo's own history is the pin. It shares the install
path with `root:NAME`, so the destination folder name is still explicit and still load-bearing.

`scripts/package-client.sh` copies the working client wholesale, so the addon reaches the zip
as soon as `client-addons.sh` has run. It does **not** regenerate the item database; if
`item_template` has changed since the last `regen.sh`, run it before cutting a pack.

## What has been verified, and what has not

Verified on this box:

* every generated Lua file parses under a Lua 5.1 parser (LuaJIT), and the whole database
  loads and answers queries in a stub harness: 46,098 rows flat, `entry[]` strictly ascending,
  `Find/Decode/IconPath` correct for 6948 Hearthstone, 49623 Shadowmourne, 25 Worn Shortsword
  and 2589 Linen Cloth; search 16–28 ms on the first query (it builds the lowercase index)
  and 1–4 ms after that; 4.7 MB of Lua heap after load, 7.7 MB once the search index exists;
* `UI.xml` and the generated `Data/Data.xml` validate against the client's own
  `Interface/FrameXML/UI.xsd`, extracted from `patch-enUS-3.MPQ`;
* every FrameXML template and API this addon touches (`FauxScrollFrameTemplate`,
  `InputBoxTemplate`, `UIPanelButtonTemplate`, `UIPanelCloseButton`, `UIDropDownMenuTemplate`,
  `FauxScrollFrame_SetOffset`, `GameTooltip:IsOwned`, `ITEM_LEVEL`, `ITEM_MIN_LEVEL`,
  `YES`/`NO`, the `INVTYPE_*` strings) exists in this client's archives;
* 4,846 of 4,851 icons resolve to a real `.blp` inside the client's MPQ chain;
* `scripts/client-addons.sh` installs the addon, and reports a missing local directory, when
  run against a throwaway client.

Needs a human in game:

* that the addon-message command channel actually round-trips on this build — `/ib status`
  should say "addon channel" a few seconds after login, not "chat command";
* that `.additem <name> <id> <count>` puts the item in the *selected* player's bags;
* the visual layout at the client's real font sizes, and that the five unresolvable icons
  fall through to the question mark instead of drawing nothing.
