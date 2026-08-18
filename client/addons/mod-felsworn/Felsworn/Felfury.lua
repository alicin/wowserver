--[[--------------------------------------------------------------------------------------------
  Felfury.lua -- show the resource the class is actually played on.

  WHY THIS FILE EXISTS AT ALL, when a resource normally needs no addon:

  Felfury is not a power type. There is exactly one DisplayPower per class and Felsworn's is
  Energy (ChrClasses.dbc), so the yellow bar under the character is Energy and cannot be
  anything else. Felfury is a STACKING SELF-AURA -- spell FS_SPELL_FELFURY, whose own
  description in the source data reads "Represents your Felfury charges" -- and the default UI
  has no concept of "this one buff among your buffs is a resource". Without this file a player
  reads their own resource by hunting for an icon in the buff tray and squinting at its stack
  count, which is not a resource bar, it is a scavenger hunt.

  WHAT IT DEPENDS ON, and the one way it silently breaks:

  UnitAura can only see an aura the server sent to the client, and the server only sends an aura
  that has a client-visible slot. SpellAuras.cpp:1088 (CanBeSentToClient) denies a slot to a
  PASSIVE aura, so the Felfury record MUST NOT carry SPELL_ATTR0_PASSIVE. If it ever does, every
  function below keeps working, finds nothing, and reports zero stacks forever -- with no error,
  because "the player has no Felfury" is a perfectly ordinary thing for this code to see.
  That is the first thing to check if the counter never moves.

  The two ids below are GENERATED. dhspells.py rewrites them from dh_spec's id allocation on
  every build, so an ability that moves blocks cannot leave this file pointing at the wrong
  spell -- which is not hypothetical: the class that previously occupied slot 10 left a stale
  91500 here, and 91500 later became a debuff, so the old jump key would have cast it.
----------------------------------------------------------------------------------------------]]

local FS_SPELL_FELFURY = 91460  -- GENERATED from dh_spec.ABILITY_BLOCKS; do not edit
local FS_SPELL_INNER_DEMON = 91480  -- GENERATED from dh_spec.ABILITY_BLOCKS; do not edit

-- Matched against the aura NAME, not the id: UnitAura in 3.3.5a returns a name, and there is no
-- UnitAuraBySpellID. Resolved once at login from the id via GetSpellInfo so that a rename in the
-- data does not need a matching edit here.
local felfuryName, innerDemonName

local Felsworn = _G.Felsworn
if not Felsworn then return end

local FelfuryTracker = {}
Felsworn.Felfury = FelfuryTracker

-- The cap is data, not a constant this file may invent: it is CumulativeAura on the Felfury
-- record, and the same number reaches the server module as FELFURY_MAX_STACKS. GENERATED for
-- exactly that reason -- it was hand-written as 5, and when the pool became 6 this file went on
-- drawing "6/5" until the generator started owning it.
local FS_FELFURY_CAP = 6  -- GENERATED from dh_spec.FELFURY_MAX_STACKS; do not edit

function FelfuryTracker:Stacks()
    if not felfuryName then
        return 0
    end
    -- "HELPFUL" and a self unit: this is our own buff. The fourth return of UnitAura is the
    -- stack count, and it is 0 rather than 1 for an aura that does not stack -- so the max(1)
    -- below is what makes a single application read as one charge instead of none.
    local name, _, _, count = UnitAura("player", felfuryName, nil, "HELPFUL")
    if not name then
        return 0
    end
    return math.max(count or 0, 1)
end

function FelfuryTracker:InnerDemonActive()
    if not innerDemonName then
        return false
    end
    return UnitAura("player", innerDemonName, nil, "HELPFUL") ~= nil
end

-- The frame. Deliberately tiny and deliberately not movable: this is a number the player reads
-- mid-rotation, and every pixel of chrome around it is a pixel that is not the number.
local frame

local function EnsureFrame()
    if frame then
        return frame
    end
    frame = CreateFrame("Frame", "FelswornFelfuryFrame", UIParent)
    frame:SetWidth(70)
    frame:SetHeight(26)
    -- Anchored above the player frame rather than centre-screen: it is a resource, and a
    -- resource belongs next to the other resources.
    frame:SetPoint("BOTTOM", PlayerFrame, "TOP", 0, -6)

    frame.text = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    frame.text:SetAllPoints(frame)
    frame.text:SetJustifyH("CENTER")
    return frame
end

function FelfuryTracker:Update()
    local f = EnsureFrame()
    local stacks = self:Stacks()
    local cap = FS_FELFURY_CAP

    if stacks <= 0 then
        -- Dimmed rather than hidden. A resource bar that disappears when empty makes "empty"
        -- and "this class does not have that" look identical, which is the state a new player
        -- is in most often.
        f.text:SetText(string.format("|cff555555%d/%d|r", 0, cap))
        return
    end

    -- Green while banking, gold at cap: the only decision Felfury actually presents is "spend
    -- now or keep building", and being at cap is the moment that decision becomes forced,
    -- because further generation is wasted.
    local colour = (stacks >= cap) and "ffffd100" or "ff32cd32"
    local suffix = self:InnerDemonActive() and "  |cffff4444*|r" or ""
    f.text:SetText(string.format("|c%s%d/%d|r%s", colour, stacks, cap, suffix))
end

function FelfuryTracker:Init()
    -- Resolved from the ids, so this file never hard-codes a display name. GetSpellInfo returns
    -- nil for an id with no client-side record, which is exactly what happens if the addon is
    -- installed without the patch archive -- so it is reported once rather than failing on
    -- every aura scan.
    felfuryName = GetSpellInfo(FS_SPELL_FELFURY)
    innerDemonName = GetSpellInfo(FS_SPELL_INNER_DEMON)

    if not felfuryName then
        Felsworn.Say("Felfury (spell " .. FS_SPELL_FELFURY .. ") is not in this client's "
            .. "Spell.dbc -- the patch archive is missing or out of date. The resource "
            .. "counter is disabled.")
        return
    end

    local watcher = CreateFrame("Frame")
    -- UNIT_AURA is the only event that fires for a stack change on an existing aura; relying on
    -- PLAYER_AURAS_CHANGED alone would miss 2 -> 3 and show a stale count for the whole fight.
    watcher:RegisterEvent("UNIT_AURA")
    watcher:SetScript("OnEvent", function(_, _, unit)
        if unit == "player" then
            FelfuryTracker:Update()
        end
    end)

    FelfuryTracker:Update()
end
