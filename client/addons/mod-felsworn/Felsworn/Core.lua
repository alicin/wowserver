--[[----------------------------------------------------------------------------------------
Felsworn -- wiring.

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
the patched row has to fill with **FELSWORN** -- spelled exactly that way, because it is the
key `CLASS_ICON_TCOORDS` and `RAID_CLASS_COLORS` are indexed by (`Constants.lua:91` and `:54`)
and
therefore the key ClassUI.lua fills in. If the generator writes anything else there, this addon
goes inert on a real Felsworn and nobody gets an error message about it. That is the single
most likely way for this file to be silently wrong, so `/dh status` prints the token it saw.

The gate covers Movement.lua only. ClassUI.lua is deliberately outside it -- see its header.

WHY THERE IS A SAVED VARIABLE AT ALL
====================================
No settings yet. The block is kept because SavedVariables must exist before the first
write, and because the resource frame will want a position when it becomes movable.
that a player may reasonably want permanently off, because it is the one that can misbehave --
if combat starts while you are in the air, your jump key stays pointed at Double Jump until the
fight ends, and there is no client-side way around that (NOTES.md has the full argument). A
per-session toggle would quietly come back every login, which for a setting whose whole purpose
is "I turned this off because it bit me" is worse than not having the toggle.
------------------------------------------------------------------------------------------]]

Felsworn = {}
local A = Felsworn

-- The ChrClasses.dbc `Filename` value for class 10. Must match what the generator writes.
A.CLASS_TOKEN = "FELSWORN"

A.isFelsworn = false     -- set at PLAYER_LOGIN, read by /dh status
A.classToken = nil          -- what UnitClass actually returned, for diagnosing the above

local DEFAULTS = {
}

-- The class colour from ClassUI.lua, so chat output matches the frames.
function A.Say(text)
    DEFAULT_CHAT_FRAME:AddMessage("|cffa330c9Felsworn|r " .. text)
end

-- Frames are cheap and this one is created at file load, which is always out of combat --
-- an addon's Lua runs during the loading screen. Nothing here is protected.
local frame = CreateFrame("Frame", "FelswornFrame", UIParent)
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")

--- Stop caring about anything. Called when the player is not a Felsworn.
-- UnregisterAllEvents rather than a `if not isFelsworn then return end` in every handler:
-- an addon that is off should cost nothing per event, and a mage in a 25-man raid sees a lot
-- of events. Movement.lua's OnUpdate is never started in the first place.
local function GoInert()
    frame:UnregisterAllEvents()
end

frame:SetScript("OnEvent", function(self, event, arg1)
    if event == "ADDON_LOADED" then
        if arg1 ~= "Felsworn" then return end
        -- SavedVariables are only guaranteed to exist from our own ADDON_LOADED onwards.
        if type(FelswornSaved) ~= "table" then FelswornSaved = {} end
        for k, v in pairs(DEFAULTS) do
            if FelswornSaved[k] == nil then FelswornSaved[k] = v end
        end
        self:UnregisterEvent("ADDON_LOADED")

    elseif event == "PLAYER_LOGIN" then
        A.classToken = select(2, UnitClass("player"))
        A.isFelsworn = (A.classToken == A.CLASS_TOKEN)
        if not A.isFelsworn then
            GoInert()
            return
        end
        -- From here on this character is ours.
        A.Felfury:Init()
    end
end)


-- ------------------------------------------------------------------------------- /dh -----

SlashCmdList["FELSWORN"] = function(msg)
    msg = string.gsub(msg or "", "^%s*(.-)%s*$", "%1")
    msg = string.lower(msg)

    if msg == "" or msg == "help" then
        A.Say("/fs status   whether the resource tracker found Felfury, and the current count")
        return
    end

    if msg == "status" then
        A.Say("class token: " .. tostring(A.classToken) ..
              (A.isFelsworn and " (this addon is active)"
                                or " (inert -- not a Felsworn)"))
        if A.isFelsworn then
            A.Say("Felfury: " .. tostring(A.Felfury:Stacks()) .. " stack(s)"
                  .. (A.Felfury:InnerDemonActive() and ", Inner Demon ACTIVE" or ""))
        end
        return
    end

    A.Say("unknown command. /fs help")
end
SLASH_FELSWORN1 = "/dh"
SLASH_FELSWORN2 = "/demonhunter"


-- Keybinding labels. Bindings.xml is picked up by the client automatically from the addon
-- folder; these three globals are what the Key Bindings panel shows for it. Set for every
-- class, not just ours: the client loads Bindings.xml regardless of who you are logged in as,
-- so gating these would only replace two readable rows with two raw binding names.
BINDING_HEADER_FELSWORN = "Felsworn"
BINDING_NAME_FELSWORN_DOUBLE_JUMP = "Double Jump"
BINDING_NAME_FELSWORN_GLIDE = "Glide"
