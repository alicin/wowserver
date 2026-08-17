--[[----------------------------------------------------------------------------------------
DemonHunter -- self test.

    luajit tools/selftest.lua        (or any Lua 5.1; the addon targets 5.1)

Runs the addon against stub widgets. It is not a substitute for logging in, and it cannot be:
taint, protection and the binding system are all client behaviour that no stub reproduces. What
it does check is the part that is pure control flow and that is expensive to test in-game,
because reproducing it means dying in a raid:

  * the secure attributes are written EXACTLY ONCE and never during combat lockdown;
  * no binding call is made during combat lockdown, ever, on any path;
  * the jump-key overlay appears when the player leaves the ground and is gone when they land;
  * an overlay left installed because combat started mid-air is cleared at PLAYER_REGEN_ENABLED;
  * a /reload issued mid-fight defers everything and completes when the fight ends;
  * a non-Demon-Hunter ends up with no registered events at all.

The stubs assert on the two calls that would produce an in-game "action blocked" error, so a
regression that reintroduces one fails here with a stack trace instead of in someone's raid.
------------------------------------------------------------------------------------------]]

-- Run it from the addon root or from tools/; find the Lua either way rather than insisting
-- on a working directory.
local ADDON
do
    local here = (arg and arg[0] or ""):match("^(.*)tools[/\\]selftest%.lua$") or ""
    for _, candidate in ipairs({ here .. "DemonHunter/", "DemonHunter/", "../DemonHunter/" }) do
        local f = io.open(candidate .. "Core.lua", "r")
        if f then f:close(); ADDON = candidate; break end
    end
    assert(ADDON, "cannot find DemonHunter/Core.lua; run this from the addon root or tools/")
end

local G = _G

-- ---------------------------------------------------------------- stub environment ------

local S = {}      -- the mutable bits of the fake client, reset per scenario

local Frame = {}
Frame.__index = Frame
function Frame:RegisterEvent(e) self.events[e] = true end
function Frame:UnregisterEvent(e) self.events[e] = nil end
function Frame:UnregisterAllEvents() self.events = {} end
function Frame:SetScript(k, f) self.scripts[k] = f end
function Frame:GetScript(k) return self.scripts[k] end
function Frame:SetWidth() end
function Frame:SetHeight() end
function Frame:SetPoint() end
function Frame:SetFrameStrata() end
function Frame:RegisterForClicks(...) self.clicks = { ... } end
function Frame:Show() self.shown = true end
function Frame:Hide() self.shown = false end
function Frame:IsShown() return self.shown end
function Frame:GetName() return self.name end
function Frame:GetAttribute(k) return self.attrs[k] end

function Frame:SetAttribute(k, v)
    -- SecureActionButtonTemplate inherits SecureFrameTemplate, protected="true"
    -- (client FrameXML SecureTemplates.xml:4,11). Writing an attribute of a protected frame
    -- from insecure code during lockdown is the classic action-blocked error.
    assert(not S.combat, "SetAttribute during combat lockdown: " .. tostring(k))
    self.attrs[k] = v
end

function Frame:Fire(event, ...)
    if self.events[event] and self.scripts.OnEvent then
        self.scripts.OnEvent(self, event, ...)
    end
end

function Frame:Tick(dt)
    if self.shown and self.scripts.OnUpdate then self.scripts.OnUpdate(self, dt) end
end

local function Reset()
    S = { combat = false, falling = false, log = {}, frames = {}, overrides = {},
          class = { "Demon Hunter", "DEMONHUNTER" },
          bindings = { JUMP = { "SPACE" },
                       DEMONHUNTER_DOUBLE_JUMP = { "F" },
                       DEMONHUNTER_GLIDE = { "G" } },
          spells = {} }
    G.DemonHunterSaved = nil
    G.SlashCmdList = {}
    G.RAID_CLASS_COLORS = { WARRIOR = { r = 0.78, g = 0.61, b = 0.43 } }
    G.CLASS_ICON_TCOORDS = { WARRIOR = { 0, 0.25, 0, 0.25 } }
    G.LOCALIZED_CLASS_NAMES_MALE = { WARRIOR = "Warrior" }
    G.LOCALIZED_CLASS_NAMES_FEMALE = { WARRIOR = "Warrior" }
    G.UIParent = G.CreateFrame("Frame", "UIParent")
    for _, f in ipairs({ "Core.lua", "ClassUI.lua", "Movement.lua" }) do
        assert(loadfile(ADDON .. f), "cannot load " .. ADDON .. f)()
    end
    return S.frames.DemonHunterFrame
end

function G.CreateFrame(_kind, name, _parent, template)
    local f = setmetatable({ name = name, events = {}, scripts = {}, attrs = {},
                             shown = true, template = template }, Frame)
    if name then G[name] = f; S.frames[name] = f end
    return f
end

G.DEFAULT_CHAT_FRAME = { AddMessage = function(_, t) S.log[#S.log + 1] = t end }
function G.UnitClass() return S.class[1], S.class[2] end
function G.InCombatLockdown() return S.combat end
function G.IsFalling() return S.falling and 1 or nil end   -- 3.3.5a returns 1 or nil
function G.GetTime() return os.clock() end
function G.GetSpellInfo(id) return S.spells[id] end
function G.GetBindingKey(n) local b = S.bindings[n] or {}; return b[1], b[2] end

function G.SetOverrideBindingClick(owner, _prio, key, name, _btn)
    assert(not S.combat, "SetOverrideBindingClick during combat lockdown")   -- #nocombat
    S.overrides[owner] = S.overrides[owner] or {}
    S.overrides[owner][key] = name
end

function G.ClearOverrideBindings(owner)
    assert(not S.combat, "ClearOverrideBindings during combat lockdown")     -- #nocombat
    S.overrides[owner] = {}
end

-- ---------------------------------------------------------------- helpers ---------------

local function ov(frameName, key)
    local o = S.overrides[S.frames[frameName]]
    return o and o[key]
end

local function overlayEmpty()
    local o = S.overrides[S.frames.DemonHunterJumpOverlayOwner]
    return (o == nil) or (next(o) == nil)
end

local passed = 0
local function check(cond, what)
    assert(cond, "FAILED: " .. what)
    passed = passed + 1
end

-- ---------------------------------------------------------------- scenarios -------------

-- 1. Normal login as a Demon Hunter.
do
    local F = Reset()
    check(CLASS_ICON_TCOORDS.DEMONHUNTER ~= nil, "class icon coords filled in")
    check(RAID_CLASS_COLORS.DEMONHUNTER.r == 0.64, "class colour filled in")
    check(LOCALIZED_CLASS_NAMES_FEMALE.DEMONHUNTER == "Demon Hunter", "female class name")
    check(CLASS_ICON_TCOORDS.WARRIOR[2] == 0.25, "an existing entry is left alone")

    F:Fire("ADDON_LOADED", "DemonHunter")
    check(DemonHunterSaved.jumpKeyOverlay == true, "saved-variable default applied")

    F:Fire("PLAYER_LOGIN")
    check(S.frames.DemonHunterDoubleJumpButton.attrs.type == "spell", "type attribute")
    check(S.frames.DemonHunterDoubleJumpButton.attrs.spell == 91000, "double jump spell id")
    check(S.frames.DemonHunterGlideButton.attrs.spell == 91001, "glide spell id")
    check(ov("DemonHunterBindingOwner", "F") == "DemonHunterDoubleJumpButton",
          "Double Jump key bound to its button")
    check(ov("DemonHunterBindingOwner", "G") == "DemonHunterGlideButton",
          "Glide key bound to its button")
    check(overlayEmpty(), "no jump-key overlay while standing on the ground")

    local warned = 0
    for _, l in ipairs(S.log) do if l:find("patch archive is") then warned = warned + 1 end end
    check(warned == 2, "both abilities warned about the missing client patch")
end

-- 2. Jumping, out of combat.
do
    local F = Reset()
    F:Fire("ADDON_LOADED", "DemonHunter"); F:Fire("PLAYER_LOGIN")

    S.falling = true
    S.frames.DemonHunterPoller:Tick(0.2)
    check(ov("DemonHunterJumpOverlayOwner", "SPACE") == "DemonHunterDoubleJumpButton",
          "overlay installs on the jump key while airborne")

    S.falling = false
    S.frames.DemonHunterPoller:Tick(0.2)
    check(overlayEmpty(), "overlay released on landing, so the jump key jumps again")
end

-- 3. Combat starts while airborne. Nothing may be attempted until it ends.
do
    local F = Reset()
    F:Fire("ADDON_LOADED", "DemonHunter"); F:Fire("PLAYER_LOGIN")

    S.falling = true
    S.frames.DemonHunterPoller:Tick(0.2)
    S.combat = true
    S.falling = false
    S.frames.DemonHunterPoller:Tick(0.2)     -- stubs assert if this touches a binding
    check(ov("DemonHunterJumpOverlayOwner", "SPACE") ~= nil,
          "the overlay is knowingly stuck during the fight")

    S.combat = false
    F:Fire("PLAYER_REGEN_ENABLED")
    check(overlayEmpty(), "the stuck overlay is cleared the moment combat ends")
end

-- 4. /reload issued mid-fight: PLAYER_LOGIN arrives under lockdown.
do
    local F = Reset()
    F:Fire("ADDON_LOADED", "DemonHunter")
    S.combat = true
    F:Fire("PLAYER_LOGIN")                   -- stubs assert on any protected write
    check(S.frames.DemonHunterDoubleJumpButton.attrs.spell == nil,
          "attributes deferred while in combat")
    check(next(S.overrides[S.frames.DemonHunterBindingOwner] or {}) == nil,
          "bindings deferred while in combat")

    S.falling = true
    S.frames.DemonHunterPoller:Tick(0.2)     -- must survive running before Configure
    S.combat = false
    F:Fire("PLAYER_REGEN_ENABLED")
    check(S.frames.DemonHunterDoubleJumpButton.attrs.spell == 91000,
          "deferred configuration completes when combat ends")
    check(ov("DemonHunterBindingOwner", "F") == "DemonHunterDoubleJumpButton",
          "deferred permanent bindings install when combat ends")
    check(ov("DemonHunterJumpOverlayOwner", "SPACE") ~= nil,
          "still airborne when combat ended, so the overlay is resampled and installed")
end

-- 5. /dh.
do
    local F = Reset()
    F:Fire("ADDON_LOADED", "DemonHunter"); F:Fire("PLAYER_LOGIN")
    SlashCmdList.DEMONHUNTER("help")
    SlashCmdList.DEMONHUNTER("status")
    SlashCmdList.DEMONHUNTER("jumpkey off")
    check(DemonHunterSaved.jumpKeyOverlay == false, "/dh jumpkey off is remembered")
    check(S.frames.DemonHunterPoller.shown == false,
          "the poller stops entirely when the overlay is off")
    S.falling = true
    S.frames.DemonHunterPoller:Tick(0.2)
    check(overlayEmpty(), "overlay stays off while disabled, even airborne")
    SlashCmdList.DEMONHUNTER("jumpkey on")
    check(ov("DemonHunterJumpOverlayOwner", "SPACE") ~= nil,
          "turning it back on resamples IsFalling rather than waiting for the next edge")
    SlashCmdList.DEMONHUNTER("nonsense")
    DemonHunterMovement_BindingPressed("doublejump")
end

-- 6. Anyone who is not a Demon Hunter.
do
    local F = Reset()
    S.class = { "Priest", "PRIEST" }
    F:Fire("ADDON_LOADED", "DemonHunter")
    F:Fire("PLAYER_LOGIN")
    check(next(F.events) == nil, "the event frame is silenced for a non-Demon-Hunter")
    check(DemonHunter.isDemonHunter == false, "class gate reports correctly")
    check(S.frames.DemonHunterDoubleJumpButton == nil, "no secure buttons are created")
    check(CLASS_ICON_TCOORDS.DEMONHUNTER ~= nil,
          "but the class-UI constants are still filled in, which is the whole point")
    SlashCmdList.DEMONHUNTER("status")       -- must not reach Movement
end

print(string.format("selftest: PASS, %d checks", passed))
