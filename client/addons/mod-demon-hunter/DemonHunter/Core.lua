--[[----------------------------------------------------------------------------------------
DemonHunter -- wiring.

The namespace, the chat helper, the saved variable, the event frame, the class gate and /dh.
The two abilities live in Movement.lua; the defensive FrameXML constants live in ClassUI.lua
and run without ever consulting this file.

THE CLASS GATE, AND WHAT IT DOES AND DOES NOT COVER
===================================================
`select(2, UnitClass("player"))` returns the class TOKEN, which the client reads out of
`ChrClasses.dbc` column `Filename` -- verified on the stock file shipped with the server:

    /srv/wow/data/dbc/ChrClasses.dbc   10 records, IDs 1..9 and 11
      ID 1  DisplayPower 1  'Warrior'       'WARRIOR'
      ID 4  DisplayPower 3  'Rogue'         'ROGUE'
      ID 6  DisplayPower 6  'Death Knight'  'DEATHKNIGHT'
      ID 11 DisplayPower 0  'Druid'         'DRUID'

ID 10 is absent, which is the hole this whole feature moves into, and `Filename` is the column
the patched row has to fill with **DEMONHUNTER** -- spelled exactly that way, because it is the
key `CLASS_ICON_TCOORDS` and `RAID_CLASS_COLORS` are indexed by (`Constants.lua:91` and `:54`)
and
therefore the key ClassUI.lua fills in. If the generator writes anything else there, this addon
goes inert on a real Demon Hunter and nobody gets an error message about it. That is the single
most likely way for this file to be silently wrong, so `/dh status` prints the token it saw.

The gate covers Movement.lua only. ClassUI.lua is deliberately outside it -- see its header.

WHY THERE IS A SAVED VARIABLE AT ALL
====================================
One boolean: `jumpKeyOverlay`. The jump-key overlay (Movement.lua) is the one behaviour here
that a player may reasonably want permanently off, because it is the one that can misbehave --
if combat starts while you are in the air, your jump key stays pointed at Double Jump until the
fight ends, and there is no client-side way around that (NOTES.md has the full argument). A
per-session toggle would quietly come back every login, which for a setting whose whole purpose
is "I turned this off because it bit me" is worse than not having the toggle.
------------------------------------------------------------------------------------------]]

DemonHunter = {}
local A = DemonHunter

-- The ChrClasses.dbc `Filename` value for class 10. Must match what the generator writes.
A.CLASS_TOKEN = "DEMONHUNTER"

A.isDemonHunter = false     -- set at PLAYER_LOGIN, read by /dh status
A.classToken = nil          -- what UnitClass actually returned, for diagnosing the above

local DEFAULTS = {
    jumpKeyOverlay = true,
}

-- The class colour from ClassUI.lua, so chat output matches the frames.
function A.Say(text)
    DEFAULT_CHAT_FRAME:AddMessage("|cffa330c9DemonHunter|r " .. text)
end

-- Frames are cheap and this one is created at file load, which is always out of combat --
-- an addon's Lua runs during the loading screen. Nothing here is protected.
local frame = CreateFrame("Frame", "DemonHunterFrame", UIParent)
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")

--- Stop caring about anything. Called when the player is not a Demon Hunter.
-- UnregisterAllEvents rather than a `if not isDemonHunter then return end` in every handler:
-- an addon that is off should cost nothing per event, and a mage in a 25-man raid sees a lot
-- of events. Movement.lua's OnUpdate is never started in the first place.
local function GoInert()
    frame:UnregisterAllEvents()
end

frame:SetScript("OnEvent", function(self, event, arg1)
    if event == "ADDON_LOADED" then
        if arg1 ~= "DemonHunter" then return end
        -- SavedVariables are only guaranteed to exist from our own ADDON_LOADED onwards.
        if type(DemonHunterSaved) ~= "table" then DemonHunterSaved = {} end
        for k, v in pairs(DEFAULTS) do
            if DemonHunterSaved[k] == nil then DemonHunterSaved[k] = v end
        end
        self:UnregisterEvent("ADDON_LOADED")

    elseif event == "PLAYER_LOGIN" then
        A.classToken = select(2, UnitClass("player"))
        A.isDemonHunter = (A.classToken == A.CLASS_TOKEN)
        if not A.isDemonHunter then
            GoInert()
            return
        end
        -- From here on this character is ours. Movement.lua registers what it needs on the
        -- same frame rather than creating a second one.
        DemonHunterMovement.Init(self)

    else
        -- UPDATE_BINDINGS / PLAYER_REGEN_ENABLED, registered by Movement.lua.
        DemonHunterMovement.OnEvent(event)
    end
end)


-- ------------------------------------------------------------------------------- /dh -----

SlashCmdList["DEMONHUNTER"] = function(msg)
    msg = string.gsub(msg or "", "^%s*(.-)%s*$", "%1")
    msg = string.lower(msg)

    if msg == "" or msg == "help" then
        A.Say("/dh status          what is bound, and to what")
        A.Say("/dh jumpkey on|off  let the jump key double jump while you are airborne")
        A.Say("keybinds: Key Bindings -> Demon Hunter")
        return
    end

    if msg == "status" then
        A.Say("class token: " .. tostring(A.classToken) ..
              (A.isDemonHunter and " (this addon is active)"
                                or " (inert -- not a Demon Hunter)"))
        if A.isDemonHunter then
            DemonHunterMovement.PrintStatus()
        end
        return
    end

    local onoff = string.match(msg, "^jumpkey%s+(%a+)$")
    if onoff == "on" or onoff == "off" then
        DemonHunterSaved.jumpKeyOverlay = (onoff == "on")
        A.Say("jump-key overlay " .. onoff ..
              ((onoff == "on") and " -- your jump key double jumps while you are in the air, "
                               .. "except during combat"
                                or " -- your jump key is left alone; use the Double Jump "
                               .. "keybind instead"))
        if A.isDemonHunter then DemonHunterMovement.SyncOverlay() end
        return
    end

    A.Say("unknown command. /dh help")
end
SLASH_DEMONHUNTER1 = "/dh"
SLASH_DEMONHUNTER2 = "/demonhunter"


-- Keybinding labels. Bindings.xml is picked up by the client automatically from the addon
-- folder; these three globals are what the Key Bindings panel shows for it. Set for every
-- class, not just ours: the client loads Bindings.xml regardless of who you are logged in as,
-- so gating these would only replace two readable rows with two raw binding names.
BINDING_HEADER_DEMONHUNTER = "Demon Hunter"
BINDING_NAME_DEMONHUNTER_DOUBLE_JUMP = "Double Jump"
BINDING_NAME_DEMONHUNTER_GLIDE = "Glide"
