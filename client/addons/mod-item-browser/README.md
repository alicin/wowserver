# mod-item-browser

A GM item browser for the 3.3.5a client: filter 46,098 items the way the auction house does,
see them with their real icons and quality colours, hover for the client's own tooltip, and
hand one to whoever you have selected.

    /ib                 toggle the window
    /ib <text>          open and search
    /ib reset           clear every filter
    /ib status          which database and which command transport is in use
    /ib chat | addon    force a command transport (escape hatch, see below)

```
client/addons/mod-item-browser/
  ItemBrowser/            <- the AddOns folder, installed verbatim as AddOns/ItemBrowser
    ItemBrowser.toc
    Data.lua                storage shape and accessors        hand-written
    Search.lua              filter + search -> row indices     hand-written
    Transport.lua           issuing the GM command             hand-written
    UI.xml / UI.lua         window, rows, tooltips, giving     hand-written
    Data/                   GENERATED -- never hand-edit
  tools/
    itemdb.py               the generator (read-only DB access)
    regen.sh                one command: emit, then re-verify
    selftest.sh             run the addon under a Lua 5.1 interpreter, against the live rows
    selftest-data.lua         part 1: the database and the filter engine
    selftest-ui.lua           part 2: UI.lua driven against widget stubs
```

## The filter bar

The stock auction house's, over the local database:

| control | source | notes |
|---|---|---|
| Name | `item_template.name` | ranked, filters as you type |
| Category | `class` | 16 categories, only the ones that hold items |
| Subcategory | `subclass` | 113 pairs, redrawn when the category changes |
| Quality | `Quality` | minimum, in the correct WoW colours |
| Level Range | `RequiredLevel` | min .. max, either end optional |
| Item level | `ItemLevel` | min .. max — the AH has no such filter and a GM wants one |
| Usable Items | class / race / level / proficiency | see below |

**The category names are not typed anywhere.** They are read at generation time from the
client's own `ItemClass.dbc` (field 3) and `ItemSubClass.dbc` (field 27 `VerboseName`, falling
back to field 10 `DisplayName`), which is exactly where the real auction house gets the strings
in its dropdowns. `VerboseName` is what distinguishes weapon subclasses 0 and 1 — `DisplayName`
calls both of them "Axe", the AH shows "One-Handed Axes" and "Two-Handed Axes". A
class/subclass pair the DBCs have never heard of (`item_template` really does contain class 15
subclass 12) is labelled by number rather than dropped, so no item is unreachable.

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

Three separate mechanisms, because there are three separate costs.

1. **The scan is chunked.** A search is a job, not a call: `Search:Begin(filter)` sets it up
   and `Search:Step(budget)` advances it by at most `budget` rows. The UI spends ~6,000 rows
   per frame, so a full unfiltered pass is eight frames of a few milliseconds each rather than
   one blocking pass. Typing is throttled to 200 ms of quiet on top of that.
2. **Fields are read out of the packed number in place** — two arithmetic ops each, no
   `Decode()` call per row — and tested most-selective-first: category, then quality, then the
   two level ranges, then the restriction lookup, then `string.find` last.
3. **The sort is only paid when it buys something.** With no name typed, results come out in
   ascending item id, which is the order the arrays are already in, so there is no sort and no
   cap. With a name typed, matches are ranked and capped at 5,000, and the sort key is packed
   into one number so `table.sort` runs on its native numeric comparator instead of calling
   back into Lua.

**Worst-case row count after filtering: 46,098** — no name, no filters, the whole catalogue.
That is fine to hold (an array of integers) and fine to page, because the window instantiates
thirteen row widgets and re-fills them from a scroll offset; the length of the result list
never changes how much drawing happens.

Measured on this box against the real 46,098 rows, under LuaJIT's *interpreter* (`-joff`,
which is the closest easily available stand-in for WoW's Lua 5.1 — still somewhat faster):

```
full table, no filter                              2.3 ms
one subcategory (Armor / Plate)                    2.6 ms
quality + required-level range                     2.4 ms
name search ("cloth")                              5.9 ms
name search past the 5,000 cap ("of", 9,695 hits)  7.8 ms
usable only                                       13.4 ms
```

Every one of those is a whole search. Chunked at 6,000 rows a frame, no single frame does more
than about an eighth of it.

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

Only the client can draw a true item tooltip — stats, sockets and their bonus, set membership
and set bonuses, durability, flavour text, the red "Requires Level" line — and only from data
the server has sent it. An addon cannot fake that and this one does not try. Three parts:

1. **Prefetch.** Every time the list is re-filled, the ids now on screen are queued. Four are
   issued every 0.2 s (so at most 20 item queries a second while you scroll), each id asked at
   most once per session. An item you have merely scrolled past is usually already cached by
   the time you hover it.
2. **Hover.** If `GetItemInfo(id)` has an answer, `GameTooltip:SetHyperlink(link)` — the
   genuine tooltip, identical to hovering the item in a bag — plus a small footer this addon
   adds: `Armor / Plate`, `id 51220`, and the equipment slot.
3. **Wait.** Otherwise the shipped summary is drawn, marked with the client's own
   `RETRIEVING_ITEM_INFO` string, and `GetItemInfo` is polled for six seconds; the moment it
   resolves the tooltip is replaced in place under the still-hovering cursor.

The polling is not laziness. Touching `GetItemInfo()` for an unknown item returns nil *and*
sends `CMSG_ITEM_QUERY_SINGLE`; the reply arrives asynchronously and 3.3.5 has no event for it
(`GET_ITEM_INFO_RECEIVED` does not exist until Mists, and there is no callback form). Polling
one id per frame is the whole available API.

**Failure modes.** If the server never answers — mid-loading-screen, dropped reply, an id the
server does not have — you keep the summary, the poll gives up after six seconds, and moving
the cursor away and back retries. The nastier one is silent: `itemcache.wdb` is keyed by item
id alone and is **not** per-realm, so a client that has played on another server with a
differently edited item 49623 answers instantly with that other server's data, and nothing an
addon can see distinguishes it. Deleting the client's `Cache/` directory is the fix.

### 4. Everything data-shaped is generated, and re-verified

Nothing about the item world is typed into the addon by hand. Category labels, skill names,
class/race bit tokens, the restriction pool and the 46,098 rows all come out of the world DB
and the DBCs. The two things that *are* literals in `itemdb.py` — the weapon and armour
proficiency arrays — are copied verbatim from `ItemTemplate.h` and compared against the pinned
checkout on every run, the same treatment `dkspells.py` gives the DBC format strings.

## Regenerating

```sh
client/addons/mod-item-browser/tools/regen.sh              # emit, then re-verify
client/addons/mod-item-browser/tools/regen.sh --icon-check # also probe the client MPQs (~25s)
scripts/client-addons.sh                                   # install into the working client
```

`regen.sh` emits and then runs `itemdb.py --check`, which re-derives everything from the DB
and byte-compares it against what is now on disk. Output is deterministic — no timestamps,
input ordered by entry, fixed shard size — so a re-run against an unchanged `item_template`
rewrites the same bytes and `--check` is a plain byte comparison. Thirteen generator
invariants are hard failures in both directions; see the module docstring in `tools/itemdb.py`.

The generator reads the world DB through the same read-only `docker compose exec mysql`
path the rest of this repo uses, and writes only into `ItemBrowser/Data/`. Pass a different
client with `-- --mysql-cmd '...'` if that path is not available.

## Testing without the game

```sh
client/addons/mod-item-browser/tools/selftest.sh            # 89 checks, about 20 seconds
client/addons/mod-item-browser/tools/selftest.sh --rows F   # reuse an existing dump
```

`regen.sh` proves the generated **bytes** are what the database would produce. `selftest.sh`
proves the addon gives the right **answers** back once the client has parsed them, and that
the window's wiring runs. It loads the real files under LuaJIT (a Lua 5.1 implementation, like
the client's) with a stub FrameXML:

* **part 1** decodes all 46,098 rows back out of the packed record and compares every field
  with a fresh `item_template` dump — taken through `itemdb.py --dump-rows`, whose `SELECT`
  deliberately lists the columns in a *different* order from the generator's, so a harness
  that read the same tuple the same way could not catch a swapped column. Then ten filter
  combinations against a direct pass over those rows, the Usable test against an independent
  reimplementation of `PlayerCanUseItem`, the name ranking, and proof that chunked stepping in
  977-row slices returns a byte-identical result list to one blocking pass;
* **part 2** drives `UI.lua`: `ADDON_LOADED`, `OnShow`, `OnUpdate` ticks until the scan
  settles, dropdown clicks, the numeric boxes, the Usable checkbox, hovering a row before and
  after the server answers, clicking one, the give bar, Reset, and every slash subcommand. It
  cannot tell you the window *looks* right — nothing there measures a pixel. It tells you
  nothing in it indexes a nil, which is the failure that otherwise costs a trip in game.

The stubs simplify freely except in two places where copying the client is the point:
`UIDropDownMenu_AddButton` falling back to `info.text` when `info.value` is nil (which is why
the "All categories" entry needs a sentinel value), and `GetSkillLineInfo`'s return order.

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
  loads and answers queries in a stub harness: 46,098 rows flat, 61 ms to load, `entry[]`
  strictly ascending, and **every one of the 46,098 rows round-trips** — name, quality,
  inventory type, class, subclass, required level, item level, allowable class, allowable
  race, required skill and rank — against a fresh `SELECT` from `item_template`;
* ten filter combinations return exactly the row count a direct pass over those same database
  rows gives, including `class + subclass + quality + required level + item level` all at
  once;
* the Usable filter matches an independent reimplementation of `PlayerCanUseItem` for three
  characters (level 80 human mage with cloth only: 20,826 items; level 80 orc warrior with the
  full set: 37,369; level 10 mage: 13,604), and an unreadable or collapsed skill list is
  permissive rather than restrictive;
* chunked stepping in 977-row slices returns byte-identical result lists to one blocking pass,
  for four different filters;
* category labels resolve as the AH shows them — 49623 → `Weapon / Two-Handed Axes`, 51220 →
  `Armor / Plate`, 39 → `Armor / Cloth`, 6948 → `Miscellaneous / Junk` — and all 113
  class/subclass pairs present in the data have one;
* `UI.xml` and the generated `Data/Data.xml` validate against the client's own
  `Interface/FrameXML/UI.xsd`, extracted from `patch-enUS-3.MPQ` with StormLib;
* every FrameXML global and API this addon touches exists in that same client: the templates
  (`FauxScrollFrameTemplate`, `InputBoxTemplate`, `UIPanelButtonTemplate`,
  `UICheckButtonTemplate`, `UIPanelCloseButton`, `UIDropDownMenuTemplate`), the dropdown
  functions (`UIDropDownMenu_Initialize/AddButton/CreateInfo/SetWidth/SetText/
  SetSelectedValue/JustifyText/EnableDropDown/DisableDropDown`), the strings (`ITEM_LEVEL`,
  `ITEM_MIN_LEVEL`, `ITEM_QUALITY0..7_DESC`, `LEVEL_RANGE`, `USABLE_ITEMS`, `RESET`,
  `RETRIEVING_ITEM_INFO`, `YES`/`NO`, the `INVTYPE_*` strings), and
  `GetNumSkillLines`/`GetSkillLineInfo` with the return signature this addon unpacks
  (`FrameXML/SkillFrame.lua:26`). Every global the addon reads was enumerated out of its own
  compiled bytecode and checked against that list, so a typo cannot hide;
* the proficiency table equals `ItemTemplate.h::GetSkill()` in the pinned core checkout;
* 4,846 of 4,851 icons resolve to a real `.blp` inside the client's MPQ chain;
* `scripts/client-addons.sh` installs the addon, and reports a missing local directory, when
  run against a throwaway client.

Needs a human in game:

* **the visual layout.** Nothing here has been rendered. Widget positions, the three dropdowns
  fitting side by side, and the label text not colliding with the boxes it labels were worked
  out on paper from the client's own template geometry;
* **that `SetHyperlink` produces the full tooltip** for the three cases it was designed
  around: a socketed epic set piece (51220 Sanctified Ymirjar Lord's Breastplate — red and
  blue sockets, item set 896 "Ymirjar Lord's Plate"), a set piece with no sockets (16437
  Marshal's Silk Footwraps, item set 388 "Field Marshal's Regalia"), and a plain grey (39
  Recruit's Pants). All three exist with that data in `item_template` and in the client's
  `ItemSet.dbc`; whether the client renders sockets and set bonuses for an item it has only
  learned about through a query is the part only the client can answer;
* that the prefetch actually warms the cache — hover a row you have never scrolled to and
  watch whether it flickers through the summary;
* that the addon-message command channel round-trips on this build — `/ib status` should say
  "addon channel" a few seconds after login, not "chat command";
* that `.additem <name> <id> <count>` puts the item in the *selected* player's bags;
* that the five unresolvable icons fall through to the question mark instead of drawing
  nothing.
