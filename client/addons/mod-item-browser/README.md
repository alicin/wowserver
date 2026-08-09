# mod-item-browser

A GM item browser for the 3.3.5a client: find any of 46,098 items with the mouse alone, see
each one with its real icon and quality colour, hover for the client's own tooltip, and hand it
to whoever you have selected.

    /ib                 toggle the window
    /ib <text>          open and search
    /ib reset           clear every filter
    /ib minimap         show or hide the minimap button
    /ib status          which database and which command transport is in use
    /ib chat | addon    force a command transport (escape hatch, see below)

There is also a **minimap button** (drag it anywhere around the ring) and a **keybind** under
Key Bindings -> Item Browser. Escape closes the window, and it remembers where it was, how big
it was, and what you had filtered.

```
client/addons/mod-item-browser/
  ItemBrowser/            <- the AddOns folder, installed verbatim as AddOns/ItemBrowser
    ItemBrowser.toc
    Data.lua                storage shape and accessors        hand-written
    Search.lua              filter + sort -> row indices       hand-written
    Transport.lua           issuing the GM command             hand-written
    UI.xml                  the window's widget tree           hand-written
    UI.lua                  filters, list, tooltips, giving    hand-written
    Tree.lua                the category tree                  hand-written
    Launcher.lua            minimap button                     hand-written
    Bindings.xml            the keybind (loaded by the client, never from the .toc)
    Data/                   GENERATED -- never hand-edit
  tools/
    itemdb.py               the generator (read-only DB access, read-only MPQ access)
    regen.sh                one command: emit, then re-verify
    uixsd.py                pulls the client's UI.xsd out of its MPQ chain
    selftest.sh             validate the layout, then run the addon under Lua 5.1
    selftest-data.lua         the database and the filter engine, against the live rows
    selftest-ui.lua           UI.lua / Tree.lua / Launcher.lua against widget stubs
```

## Finding things without touching the keyboard

"Bows between item level 10 and 15" is three clicks in the tree and two slider drags. Nothing
in the window requires typing, and everything that can be typed can also be clicked.

### The category tree

The left column is the auction house's own browse list, over the local database:

```
Weapon        6651        <- item_template.class
  Bows         308        <- item_template.subclass
    Ranged     307        <- item_template.InventoryType, named by the client
    One-Hand     1
```

Click a row to filter by it and open it; click it again to close it and hand the filter back
to its parent. That is `AuctionFrameFilter_OnClick`'s behaviour, and the rows are drawn with
the AH's own `UI-AuctionFrame-FilterBg` and `UI-AuctionFrame-FilterLines` textures, so it reads
as part of the game rather than as an addon's idea of a tree.

**None of the taxonomy is typed anywhere.** Class and subclass labels come from the client's
`ItemClass.dbc` (field 3) and `ItemSubClass.dbc` (field 27 `VerboseName`, falling back to field
10 `DisplayName`) -- exactly where the real auction house gets the strings in its dropdowns.
`VerboseName` is what distinguishes weapon subclasses 0 and 1: `DisplayName` calls both "Axe",
the AH shows "One-Handed Axes" and "Two-Handed Axes". Which subclasses exist under a class, and
which **slots** exist under a subclass, are counted off the live `item_template` at generation
time, so no branch can be opened onto an empty list. A class/subclass pair the DBCs have never
heard of (`item_template` really does contain class 15 subclass 12) is labelled by number
rather than dropped, so no item is unreachable.

Slot names are the client's own `INVTYPE_*` globals, looked up when the row is drawn, so they
are in the player's locale and identical to the words on the character pane. Several of them
share a name -- `INVTYPE_CHEST` and `INVTYPE_ROBE` are both "Chest", `INVTYPE_SHIELD` and
`INVTYPE_WEAPONOFFHAND` are both "Off Hand", `INVTYPE_RANGED` and `INVTYPE_RANGEDRIGHT` are
both "Ranged" -- so identical labels collapse into **one** row that filters on the whole set of
ids behind it. Listing them separately would show two identical rows and make picking one
silently hide half the matching items.

### Two level ranges, both spelled out

"Level" means two different numbers, so both are offered and neither is abbreviated:

* **Requires Level** -- what a character must BE to use the item. A level 12 hunter looking for
  a bow they can use today wants this one.
* **Item Level** -- the item's own power rating. Two items that both require level 80 can be
  item level 200 and item level 284.

The labels are the client's own strings for those concepts, taken from `ITEM_MIN_LEVEL` and
`ITEM_LEVEL` with the `%d` stripped, so they match the words on the tooltip you are comparing
against and they follow the client's locale.

Each range has three ways in, all writing the same state: a row of one-click bands (`1-10`,
`10-20`, ... `80+`), a slider per end (drag, or roll the wheel over it for one step at a time),
and a box you can type in. Touch any one and the other two follow. The sliders span 0 to the
live maximum -- 100 for required level, 435 for item level -- because the generator measured
the table rather than assuming 1..80.

### And the rest

| control | source | notes |
|---|---|---|
| Name | `item_template.name` | ranked; the only thing that needs a keyboard, and it is optional |
| Quality | `Quality` | minimum, in the correct WoW colours |
| Usable Items | class / race / level / proficiency | see below |
| Sort | any column | Best match, item level, required level, quality, slot, name, item id -- each way up |

Sorting is driven from two places that share one setting: the column headings (click to sort,
click again to reverse) and the Sort menu, which also holds the orders that are not columns.
The status line always says which order the list is in, in words.

**Usable Items** mirrors `AuctionHouseUsablePlayerInfo::PlayerCanUseItem`
(`.work/ac-src/src/server/game/AuctionHouse/AuctionHouseSearcher.cpp:663`) clause for clause:

* the weapon or armour proficiency implied by class+subclass — the part nothing in
  `item_template` encodes, and the reason a mage does not see plate. The class/subclass →
  skill table is copied verbatim from `ItemTemplate.h::GetSkill()` and re-derived from the
  pinned checkout on every generator run (invariant #13), so it cannot silently drift;
* `AllowableClass` and `AllowableRace`, against `UnitClass()` / `UnitRace()`. The token →
  bit-index tables come from `ChrClasses.dbc` field 55 and `ChrRaces.dbc` field 11, which hold
  literally the strings those APIs return (`"WARRIOR"`, `"Scourge"`);
* `RequiredSkill` / `RequiredSkillRank` against the player's skill lines;
* `RequiredLevel` against `UnitLevel()`.

Two honest gaps, both deliberate:

* **`RequiredSpell` is not checked.** 3.3.5 gives an addon no way to ask whether the player
  knows an arbitrary spell id, so the 120 items carrying one are treated as usable. The AH
  would hide the recipes you already know; this does not.
* **A skill list that cannot be read is ignored, not guessed.** `GetNumSkillLines()` counts
  only the lines the skill pane is currently showing, so a collapsed header hides its children
  (`FrameXML/SkillFrame.lua:420-428` checks exactly this). If any header is collapsed, the
  skill half of the test is skipped entirely rather than hiding every plate item from a
  warrior. Absence of evidence never removes a row.

Skill lines 40 and 242 do not exist in `SkillLine.dbc` and six items require them. Nobody can
have a skill the client has no record of, so those six are correctly never usable — the
generator emits `skillName[40] = false` to say so rather than quietly skipping the check.

### Staying responsive over 46,098 rows

Four separate mechanisms, because there are four separate costs.

1. **The scan is chunked.** A search is a job, not a call: `Search:Begin(filter)` sets it up
   and `Search:Step(budget)` advances it by at most `budget` rows. The UI spends ~6,000 rows
   per frame, so a full unfiltered pass is eight frames of a few milliseconds each rather than
   one blocking pass. Typing is throttled to 200 ms of quiet on top of that; a *click* (a
   category, a band, a heading) skips the throttle, because it is a decision rather than a
   half-finished word.
2. **Fields are read out of the packed number in place** -- two arithmetic ops each, no
   `Decode()` call per row -- and tested most-selective-first: category, then slot, then
   quality, then the two level ranges, then the restriction lookup, then `string.find` last.
3. **Every order is a number.** Sorting packs `value * 2^20 + rowIndex` into one integer so
   `table.sort` uses its built-in C comparator instead of calling back into Lua ~715,000 times;
   the row index in the low bits makes ties break by item id and the sort stable without a
   comparator. A-Z cannot pack a string, so up to 4,000 matches it sorts the names directly,
   and above that it builds a whole-catalogue rank **once** (~50 ms) and reuses it for the
   session.
4. **Widgets are pooled, not created.** The result rows and the tree rows are sized to the
   window -- 14 rows in the default 900x700, 25 in a tall one -- and re-filled from a scroll
   offset. Growing the window creates rows up to a cap of 40; shrinking it hides them again.
   Nothing in the window scales with the size of the database or of the result list.

**Worst-case result count: 46,098** -- no name, no filters, the whole catalogue. That is an
array of integers, and the only thing it costs beyond memory is one sort if the order is not
the default. Paging it is free, because the number of row widgets never changes.

Measured on this box against the real 46,098 rows, under LuaJIT's *interpreter* (`-joff`, the
closest easily available stand-in for WoW's Lua 5.1 -- still somewhat faster):

```
full table, no filter                              1.2 ms
one subcategory (Armor / Plate)                    1.2 ms
quality + required-level range                     1.2 ms
bows, Ranged slot, item level 10-15                1.1 ms
name search ("cloth")                              5.5 ms
name search past the 5,000 cap ("of")              6.4 ms
usable only                                        6.5 ms
one subcategory sorted by item level               1.9 ms
FULL TABLE sorted by item level                   10.1 ms
FULL TABLE sorted A-Z, rank already built         10.2 ms
  ...building that rank, once per session         51   ms
```

Every line except the last is a whole search. Chunked at 6,000 rows a frame, no single frame
does more than about an eighth of the scan; the sort is the one part that cannot be chunked,
which is why the only double-digit numbers here are the two full-table sorts.

## The four decisions worth knowing

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

**Who receives it is spelled out three times**, because a list of 46,000 items next to an
invisible target selection is the one place this addon can quietly do the wrong thing: a
`Selected: 3x <item>` line, a `Recipient: <name>` line coloured green for someone else and
white for yourself (with the reason in yellow when it falls back to you — "nothing targeted",
"your target is not a player"), and the button itself, which reads `Give to Grishnak` or
`Give to me` and is disabled until something is selected. Anything that is not "one of these,
for me" still needs a confirmation click.

### 2. The item data is shipped, not asked for

A 3.3.5a client only knows items already in its `itemcache.wdb`, so `GetItemInfo` returns nil
for essentially everything on a fresh install and a naive browser shows blank rows. `tools/itemdb.py`
bakes `acore_world.item_template` into Lua. Icons are not in `item_template`: they come from
`displayid -> ItemDisplayInfo.dbc` field 5, `inventoryIcon[0]`, read from `/srv/wow/data/dbc`.

Measured on 2026-08-08: **46,098 items, 4,851 distinct icons, 727 distinct class/race/skill
restrictions, 2,284,739 bytes across 12 files**, the largest 308 KB. Sharded at 6,000 rows
per file. (It was 2,224,587 across 11 before the filter work: +60,152 bytes, 2.7%, of which
17 KB is `Filters.lua` and the rest is the restriction index inside the packed record.) For
scale, the pinned addon set already ships a
single 5.1 MB Lua file (`Questie-335/Database/Wotlk/wotlkNpcDB.lua`), so this is comfortably
inside what this client loads — the shard budget exists to make "the database grew 10x" fail
in the generator rather than in game.

Seven fields per item are packed into one Lua number, not seven arrays:

```
meta = quality + 16*(invtype + 32*(class + 32*(subclass + 32*(reqlevel
               + 128*(itemlevel + 512*restrict)))))
```

`restrict` is the most significant field deliberately. It indexes a pool of the distinct
`(AllowableClass, AllowableRace, RequiredSkill, RequiredSkillRank)` tuples, and 0 means "no
restriction at all" — true of 32,567 of the 46,098 rows, whose packed number is therefore
byte-identical to what it was before the field existed. Only the restricted minority pays the
extra digits. The record is 46 bits wide, which is why the arithmetic is multiplication rather
than `bit.band`: WoW's LuaBitOp is 32-bit and would silently truncate the item level away.

Two icon quirks in this client's data, both found with `--icon-check` and both load-bearing:

* one display carries `INV_Chest_Fur.tga`; the archive holds `INV_Chest_Fur.blp` and nothing
  called `INV_Chest_Fur.tga.blp`, so the extension is stripped;
* three carry a **trailing space** (`"INV_Misc_Food_93_SkethylBerries "`) and the `.blp`
  inside `locale-enUS.MPQ` has the space in its filename too. Trimming breaks those icons.

Five icon names in the whole table resolve to no file at all, on six items, all of them
internal junk (`Monster - Item, Glass - Clear`, `NPC Equip 6128`, deprecated rows). The row
template keeps a question mark texture in the layer behind the icon, so those draw as a
question mark rather than as a hole.

### 3. Tooltips are the client's own, eventually

Only the client can draw a true item tooltip -- stats, sockets and their bonus, set membership
and set bonuses, "Chance on hit" procs, Use effects, durability, flavour text, the red
"Requires Level" line -- and only from data the server has sent it. An addon cannot fake that
and this one does not try. Three parts:

1. **Prefetch.** Every time the list is re-filled, the ids now on screen are queued. Four are
   issued every 0.2 s (so at most 20 item queries a second while you scroll), each id asked at
   most once per session. An item you have merely scrolled past is usually already cached by
   the time you hover it.
2. **Hover.** If `GetItemInfo(id)` returns a name, the client has the item, and
   `GameTooltip:SetHyperlink(link)` draws the genuine tooltip -- identical to hovering the item
   in a bag -- plus a small footer this addon adds: `Armor / Plate`, `id 51220`, the equipment
   slot, and a reminder that shift-click links it in chat.
3. **Wait.** Otherwise the shipped summary is drawn, marked with the client's own
   `RETRIEVING_ITEM_INFO` string, and `GetItemInfo` is polled for six seconds; the moment it
   resolves the tooltip is replaced in place under the still-hovering cursor.

**Why the gate is `GetItemInfo` and not `SetHyperlink` itself.** This is the trap.
`SetHyperlink("item:49623")` on an uncached item does not fail and does not return anything --
it draws a one-line tooltip reading "Retrieving item information", which looks like a bug in
the addon and tells you nothing. `GetItemInfo` returning a name is the only reliable "the
client has this item" test 3.3.5 offers, so it decides which of the two tooltips gets drawn.
As a second line of defence, the real path checks `GameTooltip:NumLines() > 1` afterwards and
falls back to the summary if the client drew a stub anyway, which a truncated `itemcache.wdb`
record can cause.

The polling is not laziness. Touching `GetItemInfo()` for an unknown item returns nil *and*
sends `CMSG_ITEM_QUERY_SINGLE`; the reply arrives asynchronously and 3.3.5 has no event for it
(`GET_ITEM_INFO_RECEIVED` does not exist until Mists, and there is no callback form). Polling
one id per frame is the whole available API.

**Failure modes.** If the server never answers -- mid-loading-screen, dropped reply, an id the
server does not have -- you keep the summary, the poll gives up after six seconds, and moving
the cursor away and back retries. The nastier one is silent: `itemcache.wdb` is keyed by item
id alone and is **not** per-realm, so a client that has played on another server with a
differently edited item 49623 answers instantly with that other server's data, and nothing an
addon can see distinguishes it. Deleting the client's `Cache/` directory is the fix.

### 4. Everything data-shaped is generated, and re-verified

Nothing about the item world is typed into the addon by hand. Category labels, skill names,
class/race bit tokens, the restriction pool and the 46,098 rows all come out of the world DB
and the DBCs. The two things that *are* literals in `itemdb.py` — the weapon and armour
proficiency arrays and the inventory-slot tokens — are copied verbatim from `ItemTemplate.h`
and compared, on every run, against both authorities: the core's `enum InventoryType` in the
pinned checkout, and the client's own `Interface\FrameXML\GlobalStrings.lua`, read straight out
of its MPQ chain. The two spell three slots differently (the core says `INVTYPE_SHOULDERS`, the
client's global is `INVTYPE_SHOULDER`) and the check knows that one rule and nothing else, so a
genuinely new slot cannot slip through.

## Regenerating

```sh
client/addons/mod-item-browser/tools/regen.sh              # emit, then re-verify
client/addons/mod-item-browser/tools/regen.sh --icon-check # also probe the client MPQs (~25s)
scripts/client-addons.sh                                   # install into the working client
```

`regen.sh` emits and then runs `itemdb.py --check`, which re-derives everything from the DB
and byte-compares it against what is now on disk. Output is deterministic — no timestamps,
input ordered by entry, fixed shard size — so a re-run against an unchanged `item_template`
rewrites the same bytes and `--check` is a plain byte comparison. Fifteen generator
invariants are hard failures in both directions; see the module docstring in `tools/itemdb.py`.

The generated `Data/` is **2,288,125 bytes** across 12 files (8 item shards of 210-308 KB, the
icon table, the filter metadata, `Data.xml` and `Meta.lua`). The per-file budget is 1.5 MB, and
the largest shard uses a fifth of it.

The generator reads the world DB through the same read-only `docker compose exec mysql`
path the rest of this repo uses, and writes only into `ItemBrowser/Data/`. Pass a different
client with `-- --mysql-cmd '...'` if that path is not available.

## Testing without the game

```sh
client/addons/mod-item-browser/tools/selftest.sh            # 153 checks, about 20 seconds
client/addons/mod-item-browser/tools/selftest.sh --rows F   # reuse an existing dump
```

`regen.sh` proves the generated **bytes** are what the database would produce. `selftest.sh`
proves the layout is legal, that the addon gives the right **answers** back once the client has
parsed them, and that the window's wiring runs. Three parts:

* **part 1** validates `UI.xml` and the generated `Data/Data.xml` against
  `Interface\FrameXML\UI.xsd` — the schema out of *this* client's MPQ chain, pulled by
  `tools/uixsd.py` using the generator's own MPQ reader. WoW's answer to XML it dislikes is to
  skip the file in silence, which in game is indistinguishable from an addon that failed to
  load, so this is the cheapest real check available. Skipped loudly without `xmllint` or a
  client;
* **part 2** decodes all 46,098 rows back out of the packed record and compares every field
  with a fresh `item_template` dump — taken through `itemdb.py --dump-rows`, whose `SELECT`
  deliberately lists the columns in a *different* order from the generator's, so a harness
  that read the same tuple the same way could not catch a swapped column. Then: ten filter
  combinations and six slot/level combinations against a direct pass over those rows, all 247
  class/subclass/slot triples against the same, every sort order both ways round (a
  permutation of the unfiltered set, correctly ordered, no duplicates), the Usable test
  against an independent reimplementation of `PlayerCanUseItem`, the name ranking, and proof
  that chunked stepping in 977-row slices returns a byte-identical result list to one blocking
  pass;
* **part 3** drives `UI.lua`, `Tree.lua` and `Launcher.lua`: `ADDON_LOADED`, `OnShow`,
  `OnUpdate` ticks until each scan settles, the tree down all three tiers, the sliders and
  bands, the sort headings and menu, hovering a row before and after the server answers,
  clicking one, the quantity steppers, the give bar, resizing the window, Reset, a simulated
  `/reload`, and every slash subcommand. Its headline case is the user's own sentence — "bows
  between 10 and 15", both readings, done entirely with clicks and asserting the name box was
  never touched. It cannot tell you the window *looks* right — nothing there measures a pixel.
  It tells you nothing in it indexes a nil, which is the failure that otherwise costs a trip in
  game.

The stubs simplify freely except where copying the client is the point: `SetText` firing
`OnTextChanged` (which the clear button and the box/slider pairing depend on),
`UIDropDownMenu_AddButton` falling back to `info.text` when `info.value` is nil,
`GetSkillLineInfo`'s return order, the real `INVTYPE_*` strings with their duplicates, and
`SetHyperlink` producing a multi-line tooltip for a cached item and a single line for a
half-cached one.

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

* **the layout is legal 3.3.5 XML.** `UI.xml` and `Data/Data.xml` validate against
  `Interface\FrameXML\UI.xsd` extracted from this client's `patch-enUS-3.MPQ`. That covers
  every element and attribute the new window uses, including `resizable`, the `<Slider>`s and
  the `OnSizeChanged` handler;
* **every global and every method the addon calls exists in this client.** All 61 globals read
  by the six Lua files (pulled out of their compiled bytecode, so a typo cannot hide) and all
  79 method names they call appear in the client's own extracted `Interface/FrameXML`. The two
  that do not — `SendAddonMessage` and `SetMaxResize`, both C API rather than FrameXML — were
  corroborated against addons already installed in this client (`ChatThrottleLib`, DragonUI's
  `chatmods.lua`, AceGUI's `TreeGroup`);
* every generated Lua file parses under a Lua 5.1 parser (LuaJIT), and the whole database
  loads and answers queries in a stub harness: 46,098 rows flat, ~19 ms to load, `entry[]`
  strictly ascending, and **every one of the 46,098 rows round-trips** — name, quality,
  inventory type, class, subclass, required level, item level, allowable class, allowable
  race, required skill and rank — against a fresh `SELECT` from `item_template`;
* sixteen filter combinations return exactly the row count a direct pass over those same
  database rows gives, including `class + subclass + slot + quality + required level + item
  level` all at once. The headline case is checked both ways: bows with **item** level 10-15
  is 10 rows, bows with **required** level 10-15 is 6, and the database agrees with both;
* all 247 `(class, subclass, InventoryType)` triples in the data are present in the generated
  slot tier with the right counts, and each subclass's slot counts sum to the subclass's own
  count — so no branch of the tree can be hiding items;
* every sort order, both directions, over a 4,264-row subcategory: each returns a permutation
  of the unsorted set with no duplicates and in genuinely monotone order, and a name search
  returns the same matches whichever order it is displayed in;
* the Usable filter matches an independent reimplementation of `PlayerCanUseItem` for three
  characters (level 80 human mage with cloth only: 20,826 items; level 80 orc warrior with the
  full set: 37,369; level 10 mage: 13,604), and an unreadable or collapsed skill list is
  permissive rather than restrictive;
* chunked stepping in 977-row slices returns byte-identical result lists to one blocking pass,
  for four different filters;
* category labels resolve as the AH shows them — 49623 → `Weapon / Two-Handed Axes`, 51220 →
  `Armor / Plate`, 39 → `Armor / Cloth`, 6948 → `Miscellaneous / Junk` — and all 113
  class/subclass pairs present in the data have one;
* the inventory-slot table agrees with the core's `enum InventoryType` **and** every one of its
  28 tokens names a real string in the client's `GlobalStrings.lua` (25 distinct labels: the
  duplicates are why the tree groups by label);
* the proficiency table equals `ItemTemplate.h::GetSkill()` in the pinned core checkout;
* 4,846 of 4,851 item icons resolve to a real `.blp` inside the client's MPQ chain, and so do
  all 21 UI texture paths this window uses — the AH filter background and its elbow lines, the
  chat size-grabber, the minimap ring and highlight, the sort arrow, the plus/minus steppers,
  the dialog and tooltip backdrops;
* the UI harness drives 86 checks through the real code, including a simulated `/reload` that
  restores a saved bows / Ranged / item level 10-15 / uncommon+ filter and lands on the 7 items
  the database says that is;
* `scripts/client-addons.sh` installs the addon, and reports a missing local directory, when
  run against a throwaway client.

Needs a human in game:

* **the visual layout.** Nothing here has been rendered. Widget positions, the filter line
  fitting across the top at the minimum 780px width, the two slider rows inside their box, and
  the label text not colliding with the boxes it labels were worked out from the client's own
  template geometry, not seen;
* **that `SetHyperlink` produces the full tooltip** for the four cases it was designed around:
  a socketed epic set piece (51220 Sanctified Ymirjar Lord's Breastplate — red and blue
  sockets, item set 896), a set piece with no sockets (16437 Marshal's Silk Footwraps, item set
  388), a weapon with a chance-on-hit proc (17075 Vis'kag the Bloodletter, spell 21140 with trigger 2, chance on hit),
  and a plain grey (39 Recruit's Pants). All four exist with that data in `item_template` and
  in the client's `ItemSet.dbc`; whether the client renders sockets, set bonuses and procs for
  an item it has only learned about through a query is the part only the client can answer;
* that the prefetch actually warms the cache — hover a row you have never scrolled to and
  watch whether it flickers through the summary;
* **resizing**: that dragging the grip re-flows the list and that the row count follows;
* that the minimap button lands where the drag put it after a `/reload`, and that the keybind
  shows up under Key Bindings → Item Browser;
* that the addon-message command channel round-trips on this build — `/ib status` should say
  "addon channel" a few seconds after login, not "chat command";
* that `.additem <name> <id> <count>` puts the item in the *selected* player's bags;
* that the five unresolvable icons fall through to the question mark instead of drawing
  nothing.
