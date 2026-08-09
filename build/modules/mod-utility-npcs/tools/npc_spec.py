"""Declarative spec for mod-utility-npcs. Everything a human chooses lives here.

tools/gen_spawns.py reads this, joins it against the LIVE world DB (read-only) and emits

    data/sql/db-world/base/2026_08_08_20_utility_npcs_spawns.sql
    src/utility_npcs_range.h

Nothing in this file is a coordinate. Every x/y/z/o in the finished SQL is COPIED from a row
that already exists on the realm -- an innkeeper's spawn, a `playercreateinfo` start point, or a
`game_tele` entry. That is the whole safety argument: invented coordinates land inside terrain,
under the water table or in the void, and the NPC is then unreachable or falls forever.
"""

import os

MODULE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPO_ROOT = os.path.abspath(os.path.join(MODULE_DIR, "..", "..", ".."))

SQL_DIR = os.path.join(MODULE_DIR, "data", "sql", "db-world", "base")
SQL_NAME = "2026_08_08_20_utility_npcs_spawns.sql"
SQL_PATH = os.path.join(SQL_DIR, SQL_NAME)
HEADER_PATH = os.path.join(MODULE_DIR, "src", "utility_npcs_range.h")


# ==============================================================================================
# The reserved creature.guid block
# ==============================================================================================
#
# WHY THIS BLOCK IS SAFE -- four numbers, all verified against the live realm:
#
#   MAX(guid) FROM creature ................  5,300,688   (2026-08-08, acore_world)
#   COUNT(*) WHERE guid >= 6,000,000 .......          0
#   COUNT(*) WHERE guid BETWEEN the range ..          0
#   the hard ceiling ....................... 16,777,215   = 0xFFFFFF
#
# The ceiling is not the column width. `creature.guid` is INT UNSIGNED, but
# ObjectMgr::GenerateCreatureSpawnId (ObjectMgr.cpp:7655-7662) calls World::StopNow -- the
# worldserver SHUTS DOWN -- the moment the next spawn id would reach 0xFFFFFF. So the entire
# usable id space is 1..16,777,214 and a "nice big round number like 4 billion" is a server
# that refuses to boot the first time a GM types `.npc add`.
#
# 10,000,000 sits at 60% of that space: 4.7M of untouched room below it for the upstream world
# DB to grow into (it would have to nearly double), and 6.68M above it for GM spawns.
#
# THE TOP OF THE BLOCK IS ALWAYS OCCUPIED, ON PURPOSE. ObjectMgr::LoadPersistentData seeds
# `_creatureSpawnId = MAX(guid) + 1` (ObjectMgr.cpp:7616-7618), so whatever this module's highest
# row is becomes the first id `.npc add` hands out. If we packed upward from GUID_FIRST, the very
# next GM spawn would land INSIDE the reserved range and the next generator run would delete it.
# Packing DOWNWARD from GUID_LAST pins MAX(guid) at exactly GUID_LAST for as long as this module
# has at least one spawn, so `.npc add` always starts one past the end of the block.
GUID_FIRST = 10_000_000
GUID_LAST = 10_099_999

# ObjectMgr.cpp:7657. Not a guess -- read it there before changing anything above.
SPAWN_ID_CEILING = 0xFFFFFF

# Leave at least this much of the id space above the block for `.npc add`.
MIN_HEADROOM_ABOVE = 1_000_000


# ==============================================================================================
# The NPCs
# ==============================================================================================
#
# `entry` is the ONLY thing this module asserts about them. Faction, npcflag, model, script and
# level all stay in creature_template, where the owning module put them -- see ROSTER NOTES in
# gen_spawns.py for why the spawn row deliberately writes 0 into npcflag/unit_flags/dynamicflags.

NPCS = {
    190010: ("Warpweaver", "transmogrification", "mod-transmog"),
    190011: ("Ethereal Warpweaver", "transmogrification (alternate entry)", "mod-transmog"),
    199999: ("Kaylub", "free profession training and skill-ups", "mod-npc-free-professions"),
    300000: ("Cromi", "instance and raid lockout reset", "mod-instance-reset"),
    601015: ("Beauregard Boneglitter", "enchanting service", "mod-npc-enchanter"),
    9000000: ("Gabriella", "heirlooms, glyphs, gems, enchants, bags, professions, "
                           "flight paths, lockouts", "mod-assistant"),
    # The only entry this repo owns. Defined in
    # data/sql/db-world/base/2026_08_08_21_utility_npcs_talent_master.sql rather than by a
    # third-party module, which is why it is safe for us to attach a script to it.
    9000100: ("Ysolde Ashgrave", "free talent and pet-talent respec, catch-up spell training",
              "mod-utility-npcs"),
}

# WHY THE INN AND START ROSTERS ARE FIVE AND NOT SIX.
#
# 190010 and 190011 are not two NPCs. On this realm they are the same NPC twice: same
# ScriptName (npc_transmogrifier), same subname (Transmogrifier), same faction (35), and -- the
# part that settles it -- the same CreatureDisplayID, 19646, in creature_template_model. A player
# cannot tell them apart by sight or by what they do. Standing both of them in all 122 inns would
# be 122 identical pairs of twins and 122 extra rows for no service anyone gains.
#
# So the duplicate is not dropped, it is POSTED SOMEWHERE INTERESTING: the alternate entry gets
# the fourteen surprise locations, which is where a second transmogrifier reads as a joke instead
# of as a bug. Change these three tuples and re-run; nothing else in the generator cares.
ROSTER_INN = (190010, 199999, 300000, 601015, 9000000, 9000100)
ROSTER_START = (190010, 199999, 300000, 601015, 9000000, 9000100)
ROSTER_SURPRISE = (190010, 190011, 199999, 300000, 601015, 9000000, 9000100)


# ==============================================================================================
# Ring geometry
# ==============================================================================================
#
# A ring, not a line: a line has two ends that stick out, and in a room the size of the Lion's
# Pride Inn one of those ends is always in a wall. A ring keeps the whole set inside a disc whose
# radius we control, and it degrades gracefully -- drop an NPC from the roster and the survivors
# stay where they were.
#
# THE RING IS ROTATED 30 DEGREES OFF THE ANCHOR'S FACING. The offsets below are +-30, +-90, +-150:
# nothing is ever placed at 0 (straight in front of the innkeeper, which is the lane the player
# walks up to talk to them and where the innkeeper's own click target has to stay clear) and
# nothing at 180 (straight behind, which for an innkeeper is the bar, the fireplace or the wall).
# The set fans outward from the front, so the first roster entries get the most open floor.
#
# Adjacent spacing is 2*R*sin(30 deg) = R. At R = 2.5 that is 2.5 yards between neighbours, and
# the widest bounding radius among the six models is 0.4213 (Kaylub, display 31833, from
# creature_model_info) -- so ~1.6 yards of clear air between any two of them.
# Seven slots, not six: the roster grew when the talent master was added. Still nothing at 0
# (the lane a player walks up to talk to the innkeeper) and nothing at exactly 180 (behind an
# innkeeper is the bar, the hearth or the wall). The extra pair sits at +/-125 so adjacent
# spacing stays roughly even rather than bunching two NPCs together.
ANGLE_OFFSETS_DEG = (30.0, -30.0, 70.0, -70.0, 110.0, -110.0, 150.0)

RING_RADIUS_INN = 2.5        # cramped indoor rooms
RING_RADIUS_START = 4.0      # open ground, and a starting zone should feel like a plaza
RING_RADIUS_SURPRISE = 4.0   # ditto

# Each NPC faces the anchor rather than away from it. Facing outward puts the back half of the
# ring nose-first into whatever the innkeeper has behind them; facing inward can only ever point
# them at the anchor, which is by definition standable floor. It also reads as a deliberate
# huddle rather than six strangers who happen to share a room.
FACE_INWARD = True


# ==============================================================================================
# Anchor selection
# ==============================================================================================

# UNIT_NPC_FLAG_INNKEEPER. Unit.h. This is the whole definition of "every inn" -- there is no
# `inn` table, and hand-listing inns would go stale the first time a module adds one.
NPCFLAG_INNKEEPER = 0x10000

# Two innkeeper anchors closer together than this collapse to one, keeping the earlier guid.
# Dalaran is the only place this bites (it has seven innkeeper-flagged NPCs spread over three
# floors); at 30 yards it drops exactly two of them. The point is not to save rows, it is that
# two overlapping five-NPC rings look like a bug.
MIN_ANCHOR_SEPARATION = 30.0

# Innkeepers wired to a game_event only exist while that event is running. Their inn does not
# move, so anchoring to them is still sound -- but it is worth knowing about, so the generator
# prints them rather than silently including them.
WARN_ON_EVENT_ANCHORS = True


# ==============================================================================================
# Surprise locations
# ==============================================================================================
#
# Every entry is a NAME in `game_tele`, never a coordinate. game_tele is the curated,
# GM-verified, human-named list of places on this realm; its rows were captured by someone
# standing there. But it was captured for a PLAYER teleport, which tolerates a short drop --
# a creature does not fall to the floor when it spawns, it hovers exactly where you put it.
#
# So gen_spawns.py corroborates every one against the live `creature` and `gameobject` tables --
# invariant #9 -- and refuses to emit an anchor with no existing spawn within
# CORROBORATION_DZ vertical yards. It searches the tight radius first and only widens to the
# loose one if it has to, printing a note when it does. Widening is legitimate on flat open
# ground (a spawn 60 yards away in the same desert bowl at the same z IS evidence of the floor)
# and is exactly why the two radii are separate numbers rather than one generous one.
#
# Three candidates were cut by this check. They are recorded at the bottom of this list so
# nobody re-adds them.
CORROBORATION_RADIUS = 40.0
CORROBORATION_RADIUS_LOOSE = 80.0
CORROBORATION_DZ = 5.0

SURPRISES = (
    # ---- Eastern Kingdoms -------------------------------------------------------------------
    ("TheDarkPortal",
     "Under the Dark Portal, Blasted Lands. A free-professions trainer set up directly beneath "
     "the rift that ended a world, catching everyone on their way to Outland."),
    ("Karazhan",
     "The front gates of Karazhan. Beauregard Boneglitter, an enchanter with a name like a "
     "drag act, working the door of the game's only opera house."),
    ("AeriePeak",
     "The Wildhammer gryphon roost in the Hinterlands. The best balcony in Eastern Kingdoms, "
     "and almost nobody has ever had a reason to go there."),
    ("Gnomeregan",
     "The front door of Gnomeregan. Free Engineering training, twenty feet from the largest "
     "engineering accident in Azeroth's history."),

    # ---- Kalimdor ---------------------------------------------------------------------------
    ("MirageRaceway",
     "The goblin drag strip on the Shimmering Flats. A transmogrifier at a salt-flat racetrack "
     "is exactly the right kind of stupid -- dress for the crash."),
    ("MarshalsRefuge",
     "The scientists' cave in Un'Goro Crater. Full service, surrounded by devilsaurs, run by "
     "people who are studying the devilsaurs."),
    ("CavernsOfTime",
     "The mouth of the Caverns of Time. Cromi -- who resets your instance lockouts -- literally "
     "lives at the Caverns of Time. This one is not a joke, it is a homecoming. "
     "(Corroborated at the loose radius: it is the middle of an empty desert bowl, and the "
     "nearest spawn, a Glasshide Gazer 56 yards out, sits at z 9.02 against the tele's 9.01.)"),
    ("StonetalonPeak",
     "The top of Stonetalon Mountains. Half of Kalimdor visible in one direction and a "
     "transmog vendor in the other."),

    # ---- Outland ----------------------------------------------------------------------------
    ("TheStormspire",
     "The Stormspire, Netherstorm -- a rock hanging in the Twisting Nether at z=339. The only "
     "shop counter in the game with a view of the actual void."),
    ("Skettis",
     "The arakkoa treetop city above Terokkar Forest. Birdmen. Selling outfits. In a tree."),
    ("ThroneOfKiljaeden",
     "The Throne of Kil'jaeden, the highest point in Hellfire Peninsula. Somebody has put a "
     "clothes rail on a demon lord's throne."),

    # ---- Northrend --------------------------------------------------------------------------
    ("DalaranSewer",
     "The Underbelly. A transmog fence in the sewer under the mage city, next door to the "
     "black market and the duelling pit. The single most correct placement in this file."),
    ("TempleOfStorms",
     "Thorim's hall in the Storm Peaks, z=1896 -- the highest standable floor in Northrend. "
     "You get free glyphs and the best view on the continent."),
    ("ArgentTournament",
     "The Argent Tournament grounds, Icecrown. A jousting fair with a merchant row, pitched "
     "about two hundred yards from the Lich King's front door."),
)

# CUT, and why -- so the next person does not spend an evening rediscovering it:
#
#   GurubashiArena   the funniest candidate in the file and it FAILS invariant #9 at both radii.
#                    The nearest creature spawn to game_tele 458 is the Spirit Healer 47 yards
#                    away and 8.79 yards BELOW it, which says the tele's z is the arena rim, not
#                    the pit floor. Nothing on the realm corroborates the floor height, so a
#                    Warpweaver there is a coin flip between "in the pit" and "inside the wall".
#   UnGoroCrater     game_tele 1265 sits in open crater with nothing within 80 yards and the
#                    nearest gameobject 48 yards below. MarshalsRefuge covers Un'Goro instead.
#   NetherwingLedge  corroborating spawns are 96 yards below the tele. Correct for a ledge,
#                    useless as evidence.
