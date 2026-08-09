# Utility NPCs

Six helpers are standing around the world. They are free, they are friendly, and none of them can
be attacked or will attack you. This page is who they are, what each one does for you, and every
place you can find one.

Mechanics — the guid block, the generator, the schema — live in
[`build/modules/mod-utility-npcs/README.md`](../build/modules/mod-utility-npcs/README.md). This
page is for playing.

---

## 1. Who they are

| Who | Subtitle | What they do for you |
|---|---|---|
| **Warpweaver** | Transmogrifier | Change how your gear *looks* without changing what it does. Pick an item, pick an appearance you own, done. |
| **Ethereal Warpweaver** | Transmogrifier | The same service. A second doorway to the same wardrobe — see [§5](#5-why-there-are-two-transmogrifiers). |
| **Kaylub** | Professions NPC | Free profession training and skill-ups. Everything a trainer would sell you, without the trainer or the gold. |
| **Cromi** | Instance Reset | Clears your dungeon and raid lockouts on demand. Ran Naxx and want to go again this week? He is the answer. |
| **Beauregard Boneglitter** | Enchantments | Puts enchants on your gear. No mats, no enchanter friend, no waiting in the trade channel. |
| **Gabriella** | The Assistant | The big one. Heirlooms, glyphs, gems, enchants, bags, profession skill-ups, flight paths and lockout resets, all from one gossip menu. |

Gabriella overlaps several of the others on purpose. If you only remember one name, remember hers.

They are all **friendly to both factions**. Horde and Alliance can use every one of them,
everywhere, including in each other's cities.

---

## 2. Where they are: every inn

**If a building has an innkeeper, it has these NPCs.** All 122 of them — every inn, tavern and
lodge on the realm, in both capitals and both continents and in Outland and Northrend.

| Continent | Inns |
|---|---:|
| Eastern Kingdoms | 22 |
| Kalimdor | 26 |
| Outland | 34 |
| Northrend | 40 |

They stand in a small ring around the innkeeper, about two and a half yards out, deliberately
*not* directly in front of them — so you can still walk up and set your hearthstone without
clicking a transmog vendor by mistake.

Northrend has the most because Dalaran alone has five separate innkeeper-flagged NPCs spread over
its floors and its sewer, and each one gets its own set.

Inns get five of the six: **Warpweaver, Kaylub, Cromi, Beauregard and Gabriella.**

---

## 3. Where they are: every starting zone

The same five, a few steps from where a brand-new character wakes up. Ten races, eight spots —
orcs and trolls share the Valley of Trials, dwarves and gnomes share Coldridge Valley.

| Zone | Races |
|---|---|
| Northshire, Elwynn Forest | Human |
| Coldridge Valley, Dun Morogh | Dwarf, Gnome |
| Deathknell, Tirisfal Glades | Undead |
| Valley of Trials, Durotar | Orc, Troll |
| Shadowglen, Teldrassil | Night Elf |
| Camp Narache, Mulgore | Tauren |
| Sunstrider Isle, Eversong Woods | Blood Elf |
| Ammen Vale, Azuremyst Isle | Draenei |

Gabriella is the reason this matters at level 1: heirlooms and flight paths from the first minute.

---

## 4. Where they are: the surprises

Fourteen places that are not inns. Each one has the **full set of six**. They are here because
they are funny, or because the view is worth the walk, or — in one case — because it is where the
NPC genuinely belongs.

### Eastern Kingdoms

| Place | Zone | Why |
|---|---|---|
| **The Dark Portal** | Blasted Lands | Free profession training directly beneath the rift that ended a world. Catches everybody on their way to Outland. |
| **The gates of Karazhan** | Deadwind Pass | Beauregard Boneglitter — an enchanter with a name like a drag act — working the door of the only opera house in the game. |
| **Aerie Peak** | The Hinterlands | The Wildhammer gryphon roost. Best balcony in Eastern Kingdoms, and almost nobody has ever had a reason to go there. |
| **The gates of Gnomeregan** | Dun Morogh | Free Engineering training, twenty feet from the largest engineering accident in Azeroth's history. |

### Kalimdor

| Place | Zone | Why |
|---|---|---|
| **Mirage Raceway** | Thousand Needles | The goblin drag strip on the salt flats. A transmogrifier at a racetrack is exactly the right kind of stupid — dress for the crash. |
| **Marshal's Refuge** | Un'Goro Crater | Full service, surrounded by devilsaurs, run by the people who are studying the devilsaurs. |
| **Caverns of Time** | Tanaris | Cromi resets your instance lockouts and now lives at the literal Caverns of Time. Not a joke — a homecoming. |
| **Stonetalon Peak** | Stonetalon Mountains | Half of Kalimdor in one direction and a transmog vendor in the other. |

### Outland

| Place | Zone | Why |
|---|---|---|
| **The Stormspire** | Netherstorm | A rock hanging in the Twisting Nether, 339 yards up. The only shop counter in the game with a view of the actual void. |
| **Skettis** | Terokkar Forest | Birdmen. Selling outfits. In a tree. |
| **Throne of Kil'jaeden** | Hellfire Peninsula | The highest point in Hellfire. Somebody has put a clothes rail on a demon lord's throne. |

### Northrend

| Place | Zone | Why |
|---|---|---|
| **The Underbelly** | Dalaran sewers | A transmog fence in the sewer under the mage city, next door to the black market and the duelling pit. The most correct placement on this list. |
| **Temple of Storms** | The Storm Peaks | Thorim's hall, 1,896 yards up — the highest floor you can stand on in Northrend. Free glyphs and the best view on the continent. |
| **Argent Tournament** | Icecrown | A jousting fair with a merchant row, pitched about two hundred yards from the Lich King's front door. |

Every one of these is a named `.tele` destination, so a GM can drop you at any of them instantly.

---

## 5. Why there are two transmogrifiers

Warpweaver and Ethereal Warpweaver are the same NPC with two entry numbers — same model, same
menu, same everything a player can see. Rather than stand identical twins in all 122 inns, the
second one got the fourteen surprise locations. If you find two transmog vendors somewhere, that
is why, and it does not matter which one you click.

---

## 6. Notes and known rough edges

**They can crowd a small inn.** Five NPCs in a ring around an innkeeper is comfortable in the
Legerdemain Lounge and snug in a one-room roadhouse. They are placed on the innkeeper's own floor
height, so none of them is floating or sunk, but in the tightest inns one of the ring may end up
half inside a bar counter. It is cosmetic — they are still clickable — and any individual one can
be nudged by a GM. Report them and they will be moved.

**One inn is seasonal.** The Shattered Sun staging area on the Isle of Quel'Danas has an innkeeper
that only exists while that world event is running. The utility NPCs there are permanent, so you
may find them standing in an otherwise empty inn. That is expected, not a bug.

**They cannot be attacked and cannot be duelled into.** They are on the neutral friendly faction,
so nothing they do can flag you or aggro you.

**Turning them off.** `UtilityNPCs.Enable = 0` in `conf/modules/mod_utility_npcs.conf` hides all
734 of them from players (GMs still see them) and takes full effect after a worldserver restart.
It does not delete anything.
