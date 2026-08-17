--[[----------------------------------------------------------------------------------------
DemonHunter -- the three FrameXML tables an eleventh class breaks.

THIS FILE IS NOT CLASS-GATED, ON PURPOSE.
=========================================
The character who gets the nil-index error is not the Demon Hunter. It is the priest who
invites one to a party, because party and raid frames colour and icon their rows by the class
token of the UNIT, not of the player:

    RAID_CLASS_COLORS[token].r          -- nil index if token is unknown
    CLASS_ICON_TCOORDS[token]           -- unpack(nil) if token is unknown
    LOCALIZED_CLASS_NAMES_MALE[token]   -- silently nil, prints "nil" in a tooltip

So a class gate here would protect exactly the one player who never needed protecting. Every
character on the realm loads this, Demon Hunter or not, and it costs three table writes.

WHY IT IS DEFENSIVE RATHER THAN AUTHORITATIVE
=============================================
The realm ships a patched `Interface\FrameXML\Constants.lua` inside its client patch, and that
file is the real source of these values -- it has to be, because `Constants.lua:83` computes

    MAX_CLASSES = #CLASS_SORT_ORDER;

at load time and several FrameXML files walk `CLASS_SORT_ORDER` while loading, i.e. before any
addon exists. `client/tools/patch-wow-exe.py` says the same thing in its docstring (lines
60-65) and it is the reason both signature checks are patched, not just the GlueXML one.

This file therefore only fills in what is ABSENT. On a correctly patched client every one of
these `if not ...` tests is false and the file does nothing. It earns its place on the client
that is missing the MPQ, running a stock `Constants.lua`, or on the day somebody rebuilds the
patch and forgets Constants.lua -- the failure mode there is a Lua error storm in the party
frames every time a Demon Hunter zones in, which reads like an addon bug and is not one.

Deliberately NOT touched: `CLASS_SORT_ORDER` and `MAX_CLASSES`. Appending to the sort order
here would change `#CLASS_SORT_ORDER` after `MAX_CLASSES` was already computed from it, so the
two would disagree for the rest of the session -- strictly worse than the missing entry.
That pair is the patched Constants.lua's job and nobody else's.

THE VALUES
==========
  colour     A330C9, the Demon Hunter class colour. NOT read out of any file in this repo --
             there is no 3.3.5a source for it, because the class does not exist in 3.3.5a.
             It is the value the class shipped with in retail, recorded here so the addon,
             the patched Constants.lua and any future generator agree on one number.
  tcoords    {0.5, 0.75, 0.5, 0.75} -- the next unused cell of the 4x4 grid in
             `Constants.lua:91-102`. Row 3 there is PALADIN {0, 0.25, 0.5, 0.75} then
             DEATHKNIGHT {0.25, .5, 0.5, .75}; this is the cell immediately after them, and it
             is untrimmed like both of its neighbours (rows 1 and 2 use trimmed edges such as
             0.49609375 = 127/256; row 3 does not).
             WHOEVER SHIPS THE CLASS ICON ATLAS MUST PUT THE DEMON HUNTER ICON IN THAT CELL.
             This constant and that .blp are one decision expressed in two places.
  names      "Demon Hunter", male and female. On a client whose ChrClasses.dbc has the class 10
             record these are already correct: `Constants.lua:87-88` calls
             FillLocalizedClassList, which reads the DBC, so this branch is the missing-MPQ
             case again.
------------------------------------------------------------------------------------------]]

local TOKEN = "DEMONHUNTER"

-- Each table is tested for existence before being indexed. That looks paranoid for globals
-- FrameXML always defines -- but the whole reason this file exists is the client where
-- FrameXML is not what we think it is, and a nil-index here would abort the rest of the load.

if type(RAID_CLASS_COLORS) == "table" and not RAID_CLASS_COLORS[TOKEN] then
    -- 0xA3/255, 0x30/255, 0xC9/255, rounded to two places the way the stock entries are
    -- (Constants.lua:54-64 uses two-decimal literals throughout).
    RAID_CLASS_COLORS[TOKEN] = { r = 0.64, g = 0.19, b = 0.79 }
end

if type(CLASS_ICON_TCOORDS) == "table" and not CLASS_ICON_TCOORDS[TOKEN] then
    CLASS_ICON_TCOORDS[TOKEN] = { 0.5, 0.75, 0.5, 0.75 }
end

if type(LOCALIZED_CLASS_NAMES_MALE) == "table"
   and not LOCALIZED_CLASS_NAMES_MALE[TOKEN] then
    LOCALIZED_CLASS_NAMES_MALE[TOKEN] = "Demon Hunter"
end

if type(LOCALIZED_CLASS_NAMES_FEMALE) == "table"
   and not LOCALIZED_CLASS_NAMES_FEMALE[TOKEN] then
    LOCALIZED_CLASS_NAMES_FEMALE[TOKEN] = "Demon Hunter"
end
