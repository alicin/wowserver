--[[----------------------------------------------------------------------------------------
DemonHunter -- double jump and glide.

Two abilities, one mechanism: a named SecureActionButtonTemplate button per ability, plus an
override binding that makes a key CLICK that button. Everything awkward in this file follows
from one sentence:

    This addon never casts anything. It arranges for the CLIENT to cast, from a keypress,
    through a button whose attributes were written while out of combat.

WHY NOT SNIFF THE KEY
=====================
The obvious shape -- a frame with :EnableKeyboard(true) that watches for the jump key and
re-sends it when it does not want it -- needs SetPropagateKeyboardInput, and this client build
does not have it. Searched for as a NUL-delimited symbol in
`/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Wow.exe`: **0 occurrences**, against
`CastSpellByID` at 0x609408, `IsFalling` at 0x61d678, `GetBindingKey` at 0x60d408 and
`SetOverrideBindingClick` at 0x60d430, all present in the same .rdata symbol block. A keyboard
frame without it swallows every key it is shown for, including the chat key. Not an option.

WHY A SECURE BUTTON
===================
`SECURE_ACTIONS.spell` in the client's own FrameXML (`Interface\FrameXML\SecureTemplates.lua`,
the `SECURE_ACTIONS.spell` entry) is:

    local spell = SecureButton_GetModifiedAttribute(self, "spell", button);
    local spellID = tonumber(spell);
    if ( spellID) then
        CastSpellByID(spellID, unit);
    elseif ( spell ) then
        CastSpellByName(spell, unit);
    end

Two things fall straight out of that.

  * A NUMBER in the `spell` attribute reaches `CastSpellByID`, so this addon never has to look
    a name up. That matters here more than usual: `GetSpellInfo` on a custom id returns nil on
    a client without the realm's patch archive, and a name-based button would then silently
    bind to nothing. An id-based button binds to the id whether the client can render it or
    not, and the missing-archive case gets an explicit warning at login instead.
  * That call is reached from `SecureActionButton_OnClick`, which the client invokes itself
    when a binding says CLICK. Reached from our Lua instead, it is a protected call from
    tainted code and is refused.

WHY OVERRIDE BINDINGS AND NOT ATTRIBUTE SWAPS
=============================================
`SecureActionButtonTemplate` inherits `SecureFrameTemplate`, which is declared
`protected="true"` (`Interface\FrameXML\SecureTemplates.xml:4,11`). Attributes of a protected
frame cannot be written by insecure code during combat lockdown. So the naive design -- one
permanently bound button whose `spell` attribute is set when airborne and cleared when
grounded -- has a fatal property: whatever the attribute happens to say when combat starts is
what it says for the whole fight.

Worse, clearing `spell` does not restore the jump. The override binding is still installed, so
a grounded press clicks a button that does nothing, and the player simply cannot jump.

So this file swaps the BINDING, not the attribute:

  * attributes are written exactly once, out of combat, and never touched again;
  * the jump key is taken over only while the player is actually airborne, and released the
    moment they land.

That inverts the failure: the state we want during combat (no override, jump key jumps) is the
same state we want while grounded, so freezing the grounded state is harmless. Only the narrow
"combat started while I was in the air" window is left, and NOTES.md accounts for it.

WHY IT CANNOT BE DRIVEN BY A SECURE SNIPPET
===========================================
The full argument is in NOTES.md; the short version, all read out of this client's FrameXML:

  * a snippet can rebind keys in combat -- `RestrictedFrames.lua:525-585` exposes
    `ClearBindings`/`SetBindingClick` into the restricted environment for exactly that -- so
    the mechanism exists;
  * but a snippet cannot find out that the player is airborne. `IsFalling` is not in
    `RESTRICTED_FUNCTIONS_SCOPE` (`RestrictedEnvironment.lua:99-183`), there is no `falling`
    macro conditional (the conditional keyword table in Wow.exe runs 0x00a1d24c to 0x00a1d334
    and is immediately followed by the source path `.\UIMacroOptions.cpp` at 0x00a1d33c: 26
    keywords, ending dead/harm/help/exists. `flying`, `swimming`, `mounted` and `indoors` are
    in it; `falling` is not, and the string does not occur anywhere in the binary), and
    insecure code cannot hand the value in during combat -- writing it to the
    protected handler is blocked by lockdown, and reading it from an unprotected frame fails
    inside the snippet at `RestrictedFrames.lua:142-155`, where `GetHandleFrame` refuses any
    frame that is not explicitly protected while `InCombatLockdown()`.

So the snippet route buys nothing this file does not already have, and costs a restricted
environment nobody can debug. It is not used.
------------------------------------------------------------------------------------------]]


-- =========================================================================================
-- GENERATED SPELL IDS -- dhspells.py rewrites these two lines from dh_spec.SINGLES_ORDER.
--
-- The addon has to name these two spells by NUMBER: it casts them through a secure action
-- button, and there is no way to look a spell up by name from Lua that is safe in combat. That
-- makes these a third copy of an id that already exists in dh_spec.py and in Spell.dbc, so the
-- generator writes them rather than a human -- and then reads the file back and asserts both
-- numbers, so a regex that silently matched nothing cannot pass.
--
-- It has been wrong once. The file shipped with 91000 and 91001, and **91000 is not a spare
-- id, it is Demon's Bite**: pressing jump in mid-air would have swung at whatever you were
-- looking at. 91001 does not exist at all, so Glide would have silently done nothing. Neither
-- failure logs anything. That is why this is generated and not a comment asking someone to
-- remember.
--
-- `/dh status` still prints whether the client's Spell.dbc actually has each id, which is the
-- check that catches a client running an older patch-Z than the server.
local DH_SPELL_DOUBLE_JUMP = 91500      -- GENERATED from dh_spec.SINGLES_ORDER; do not edit
local DH_SPELL_GLIDE       = 91501      -- GENERATED from dh_spec.SINGLES_ORDER; do not edit
-- =========================================================================================


DemonHunterMovement = {}
local M = DemonHunterMovement
local A = DemonHunter

-- How often IsFalling() is sampled, in seconds. 20 Hz is one C call per 50 ms, which is
-- nothing, and it bounds how long after leaving the ground the jump key is still a plain
-- jump. A human cannot press space twice inside 50 ms; if they somehow do, the second press
-- is an ordinary airborne jump, which the client ignores. Nothing is lost, nothing misfires.
local POLL = 0.05

local ABILITIES = {
    doublejump = {
        label      = "Double Jump",
        spell      = DH_SPELL_DOUBLE_JUMP,
        binding    = "DEMONHUNTER_DOUBLE_JUMP",
        frameName  = "DemonHunterDoubleJumpButton",
    },
    glide = {
        label      = "Glide",
        spell      = DH_SPELL_GLIDE,
        binding    = "DEMONHUNTER_GLIDE",
        frameName  = "DemonHunterGlideButton",
    },
}
-- Deterministic order for the two places that print or iterate.
local ORDER = { "doublejump", "glide" }

local buttons = {}          -- key -> Button
local permOwner             -- owner of the permanent per-ability overrides
local overlayOwner          -- owner of the transient jump-key override
local poller                -- OnUpdate frame; only shown while the overlay is enabled

local configured = false    -- attributes written; false until we get an out-of-combat moment
local airborne = false      -- last sampled IsFalling()
local overlayKeys = nil     -- string describing the keys currently taken over, or nil
local warnedNoOverride = 0  -- GetTime() of the last "could not bind" message


-- ------------------------------------------------------------------- widgets ------------

local function CreateWidgets()
    -- Two SEPARATE owner frames. ClearOverrideBindings takes an owner and clears everything
    -- that owner installed, so putting the permanent bindings and the transient jump-key
    -- overlay on one owner would mean every landing also wiped the player's Double Jump and
    -- Glide keys. Two owners, two independent lifetimes.
    permOwner    = CreateFrame("Frame", "DemonHunterBindingOwner", UIParent)
    overlayOwner = CreateFrame("Frame", "DemonHunterJumpOverlayOwner", UIParent)

    for _, key in ipairs(ORDER) do
        local a = ABILITIES[key]
        local b = CreateFrame("Button", a.frameName, UIParent,
                              "SecureActionButtonTemplate")
        -- Left visible, not :Hide()n. The binding system reaches this button by NAME through
        -- a CLICK action, and a shown 1x1 button is the shape every click-cast addon on this
        -- client uses; a hidden one is a class of bug nobody wants to be debugging mid-fight.
        -- 1x1 in the bottom-left corner with no textures is invisible in practice.
        b:SetWidth(1)
        b:SetHeight(1)
        b:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", 0, 0)
        b:SetFrameStrata("BACKGROUND")
        -- Fire on key DOWN, matching the stock JUMP binding, which acts on keystate "down"
        -- (client FrameXML Bindings.xml, the JUMP entry). "AnyDown" is a value this build
        -- knows: the strings "AnyUp" and "AnyDown" sit adjacent in Wow.exe at 0x69f38f and
        -- 0x69f397, and FrameXML uses RegisterForClicks("AnyUp") in AudioOptionsPanels.xml.
        b:RegisterForClicks("AnyDown")
        buttons[key] = b
    end

    -- Parented and shown, because only a shown frame runs OnUpdate. Created here rather than
    -- at file load so a non-Demon-Hunter never has one at all.
    poller = CreateFrame("Frame", "DemonHunterPoller", UIParent)
    poller:Hide()
end


-- ------------------------------------------------------------------- bindings -----------

--- Install a priority override on every key bound to `bindingName`.
-- GetBindingKey returns up to two keys; both are taken, because a player who bound two keys
-- to Double Jump meant both of them.
local function BindAbility(owner, a)
    local k1, k2 = GetBindingKey(a.binding)
    if k1 then SetOverrideBindingClick(owner, true, k1, a.frameName, "LeftButton") end
    if k2 then SetOverrideBindingClick(owner, true, k2, a.frameName, "LeftButton") end
end

--- Re-install the permanent per-ability bindings from scratch.
-- SetOverrideBindingClick and ClearOverrideBindings are both #nocombat -- they are the calls
-- Blizzard had to re-expose inside the restricted environment (RestrictedFrames.lua:525-585)
-- precisely because ordinary code cannot make them during a fight. Calling one in combat
-- raises an action-blocked error, so the guard is not optional.
local function SyncPermanent()
    if InCombatLockdown() then return end
    ClearOverrideBindings(permOwner)
    for _, key in ipairs(ORDER) do
        BindAbility(permOwner, ABILITIES[key])
    end
end

--- Put the jump-key overlay into the state `want` asks for.
-- Clear-and-reinstall rather than incremental, because the JUMP binding itself can change
-- under us (UPDATE_BINDINGS) and tracking which keys we took over last time is more state
-- than this is worth. Only ever called on a transition, never per poll.
local function ApplyOverlay(want)
    if InCombatLockdown() then return end   -- #nocombat; frozen until PLAYER_REGEN_ENABLED

    if overlayKeys then
        ClearOverrideBindings(overlayOwner)
        overlayKeys = nil
    end
    if not want then return end

    local k1, k2 = GetBindingKey("JUMP")
    if not k1 then return end               -- jump unbound: nothing to take over
    SetOverrideBindingClick(overlayOwner, true, k1, ABILITIES.doublejump.frameName,
                            "LeftButton")
    if k2 then
        SetOverrideBindingClick(overlayOwner, true, k2, ABILITIES.doublejump.frameName,
                                "LeftButton")
    end
    overlayKeys = k2 and (k1 .. ", " .. k2) or k1

    -- Note what this costs while installed: the stock JUMP binding is runOnUp and calls
    -- AscendStop() on key release, and our override replaces the whole binding, so that
    -- release handler does not run. It does not matter, because the overlay only exists
    -- while IsFalling() is true, and IsFalling() is false while swimming or on a flying
    -- mount -- the only two states where ascend/descend has anything to stop.
end

--- The public entry point: recompute what the overlay should be and get there.
function M.SyncOverlay()
    if not configured then return end

    local enabled = DemonHunterSaved and DemonHunterSaved.jumpKeyOverlay
    if enabled then
        poller:Show()                       -- a hidden frame does not run OnUpdate
    else
        poller:Hide()
    end

    -- Resample rather than trusting the cached edge. The poller does not run while it is
    -- hidden, and it is hidden in exactly the two cases where this call matters most: the
    -- overlay was switched off and back on, or configuration was deferred because the player
    -- /reloaded mid-fight. In both, `airborne` is whatever it was minutes ago.
    airborne = IsFalling() and true or false
    ApplyOverlay(enabled and airborne or false)
end


-- ------------------------------------------------------------------- polling ------------

local accum = 0
local function OnUpdate(self, elapsed)
    accum = accum + elapsed
    if accum < POLL then return end
    accum = 0

    -- 3.3.5a's Is* functions return 1 or nil, not true or false. Normalise before comparing,
    -- or the edge test below fires on every single poll.
    local now = IsFalling() and true or false
    if now == airborne then return end
    airborne = now
    ApplyOverlay(DemonHunterSaved.jumpKeyOverlay and airborne or false)
end


-- ------------------------------------------------------------------- lifecycle ----------

--- Write the secure attributes. Must not run in combat; returns false if it could not.
local function Configure()
    if InCombatLockdown() then return false end
    for _, key in ipairs(ORDER) do
        local a = ABILITIES[key]
        buttons[key]:SetAttribute("type", "spell")
        -- A number, so SECURE_ACTIONS.spell takes the CastSpellByID branch. No `unit`
        -- attribute is set: SecureActionButton_OnClick passes unit = nil through to
        -- CastSpellByID, which is what a self-targeted movement spell wants, and its
        -- "unit does not exist" early-out only triggers when a unit attribute IS set.
        buttons[key]:SetAttribute("spell", a.spell)
    end
    configured = true
    return true
end

--- One line per ability if the client cannot see the spell at all.
-- Same failure as docs/death-knights.md 4.6: the server hands out a spell id that the
-- client's Spell.dbc has never heard of, so there is no name, no icon and no cast. Saying so
-- once at login is the difference between "my keybind is broken" and "I am missing the patch".
local function WarnIfSpellsMissing()
    for _, key in ipairs(ORDER) do
        local a = ABILITIES[key]
        if not GetSpellInfo(a.spell) then
            A.Say("|cffff4040" .. a.label .. " (spell " .. a.spell ..
                  ") is not in this client's Spell.dbc.|r The realm's patch archive is "
                  .. "missing or out of date -- the key will do nothing. See docs/client.md.")
        end
    end
end

--- Called from Core.lua at PLAYER_LOGIN, only for a real Demon Hunter.
-- @param eventFrame  Core's frame; we register our two extra events on it rather than making
--                    a second event frame for two rarely-firing events.
function M.Init(eventFrame)
    CreateWidgets()
    poller:SetScript("OnUpdate", OnUpdate)

    eventFrame:RegisterEvent("UPDATE_BINDINGS")
    eventFrame:RegisterEvent("PLAYER_REGEN_ENABLED")

    -- PLAYER_LOGIN normally fires during a loading screen, where InCombatLockdown() is false.
    -- It does NOT on a /reload issued mid-fight, and that is a real thing people do. In that
    -- case every call below is unavailable, so leave `configured` false and let
    -- PLAYER_REGEN_ENABLED finish the job -- rather than firing four action-blocked errors
    -- into the middle of somebody's pull.
    if Configure() then
        SyncPermanent()
        M.SyncOverlay()
    end
    WarnIfSpellsMissing()
end

function M.OnEvent(event)
    if event == "PLAYER_REGEN_ENABLED" then
        -- Lockdown just lifted. Everything #nocombat that was refused during the fight --
        -- the first-time Configure after a combat /reload, a binding change, and above all a
        -- jump-key overlay left installed because combat started while airborne -- is
        -- settled here, in that order.
        if not configured then
            if not Configure() then return end
        end
        SyncPermanent()
        M.SyncOverlay()

    elseif event == "UPDATE_BINDINGS" then
        -- Fires on load and whenever the player changes a key. Bindings cannot be edited in
        -- combat, but the event is not contractually barred from arriving then, and both
        -- calls below are #nocombat, so both are guarded internally.
        SyncPermanent()
        M.SyncOverlay()
    end
end


-- ------------------------------------------------------------------- diagnostics --------

--- Bodies of the two <Binding> entries in Bindings.xml.
-- Reached ONLY when the priority override for that key is absent, because an override wins
-- over the normal binding. So this is never the happy path: it means SetOverrideBindingClick
-- had not run for this key yet, which in practice means the key was bound during combat.
-- Throttled, because a player who does not read chat will hold the key down.
function DemonHunterMovement_BindingPressed(which)
    local a = ABILITIES[which]
    if not a then return end
    if not A.isDemonHunter then
        A.Say("that keybind only does something on a Demon Hunter.")
        return
    end
    local now = GetTime()
    if now - warnedNoOverride < 5 then return end
    warnedNoOverride = now
    A.Say(a.label .. " is not bound to its secure button yet. Key bindings cannot be "
          .. "installed during combat -- it will start working when you leave combat.")
end

function M.PrintStatus()
    A.Say("attributes written: " .. tostring(configured)
          .. (configured and "" or "  (waiting to leave combat)"))
    for _, key in ipairs(ORDER) do
        local a = ABILITIES[key]
        local k1, k2 = GetBindingKey(a.binding)
        local keys = k1 and (k2 and (k1 .. ", " .. k2) or k1) or "UNBOUND"
        local name = GetSpellInfo(a.spell)
        A.Say(string.format("%-12s spell %d %s   key: %s", a.label, a.spell,
                            name and ("(" .. name .. ")")
                                 or "|cffff4040(NOT IN THIS CLIENT'S Spell.dbc)|r",
                            keys))
    end
    local jump1, jump2 = GetBindingKey("JUMP")
    A.Say("jump key: " .. (jump1 and (jump2 and (jump1 .. ", " .. jump2) or jump1)
                                  or "UNBOUND")
          .. "   overlay: "
          .. ((DemonHunterSaved and DemonHunterSaved.jumpKeyOverlay) and "enabled"
                                                                     or "disabled by /dh")
          .. (overlayKeys and ("   ACTIVE on " .. overlayKeys) or "   idle"))
    A.Say("airborne: " .. tostring(airborne)
          .. "   in combat: " .. tostring(InCombatLockdown() and true or false))
end
