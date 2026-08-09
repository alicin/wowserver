--[[----------------------------------------------------------------------------------------
ItemBrowser self-test, part 2: the UI wiring.

    tools/selftest.sh                          dump the rows and run both parts
    luajit tools/selftest-ui.lua <rows.tsv>    just this part

Drives UI.lua for real against widget stubs: ADDON_LOADED, OnShow, OnUpdate ticks until the
scan settles, dropdown clicks, the level and item-level boxes, the Usable checkbox, row hover
before and after the server answers, row click, the give bar, Reset, and every slash
subcommand.

It cannot tell you the window LOOKS right -- nothing here measures a pixel. It tells you that
nothing in it indexes a nil, which is the failure that otherwise costs a trip in game.

The stubs simplify freely EXCEPT in two places where copying the client is the whole point:
  * UIDropDownMenu_AddButton falls back to info.text when info.value is nil
    (UIDropDownMenu.lua:336-342). That is why the "All categories" entry needs a sentinel
    value, and a stub that returned nil would hide the bug.
  * GetSkillLineInfo returns skillName, isHeader, isExpanded, skillRank in that order
    (FrameXML/SkillFrame.lua:26).
------------------------------------------------------------------------------------------]]

-- No database dump needed here: part 2 checks wiring, not data.
local ADDON = (debug.getinfo(1, "S").source:sub(2):match("(.*)/[^/]*$") or ".") .. "/../ItemBrowser"

local pass, fail = 0, 0
local function check(cond, msg)
    if cond then pass = pass + 1; print("  ok   " .. msg)
    else fail = fail + 1; print("  FAIL " .. msg) end
end

-- Anything the addon "says" -- chat lines, static popups -- lands here instead of a screen.
local log = {}
local function note(...) log[#log + 1] = table.concat({ ... }, " ") end

-- ------------------------------------------------------------------- widget stubs
local Widget = {}
Widget.__index = Widget
local function widget(name)
    return setmetatable({ _name = name, _text = "", _shown = true, _checked = false,
                          _enabled = true, _scripts = {} }, Widget)
end
function Widget:GetName() return self._name end
function Widget:SetText(t) self._text = t end
function Widget:GetText() return self._text end
function Widget:SetChecked(v) self._checked = v and true or false end
function Widget:GetChecked() return self._checked and 1 or nil end
function Widget:Show() self._shown = true end
function Widget:Hide() self._shown = false end
function Widget:IsShown() return self._shown end
function Widget:Enable() self._enabled = true end
function Widget:Disable() self._enabled = false end
function Widget:SetTexture(t) self._texture = t end
function Widget:SetValue(v) self._value = v end
function Widget:GetValue() return self._value or 0 end
function Widget:SetFocus() end
function Widget:ClearFocus() end
function Widget:SetPoint() end
function Widget:GetPoint() return "CENTER", nil, "CENTER", 0, 0 end
function Widget:ClearAllPoints() end
function Widget:SetFrameLevel() end
function Widget:GetFrameLevel() return 1 end
function Widget:EnableMouseWheel() end
function Widget:RegisterForDrag() end
function Widget:RegisterEvent() end
function Widget:SetScript(k, f) self._scripts[k] = f end
function Widget:StartMoving() end
function Widget:StopMovingOrSizing() end
function Widget:SetWidth() end

-- Any ItemBrowser* / INVTYPE_* global is manufactured on demand, so the XML's widget tree
-- does not have to be transcribed. Everything else reads as nil, the way it would in game.
setmetatable(_G, { __index = function(t, k)
    if type(k) == "string" and (k:find("^ItemBrowserFrame") or k:find("^INVTYPE_")) then
        local v = k:find("^INVTYPE_") and k:sub(9) or widget(k)
        rawset(t, k, v)
        return v
    end
    return nil
end })

function CreateFrame(_, name, _, _)
    local f = widget(name)
    if name then rawset(_G, name, f) end
    return f
end

-- ------------------------------------------------------------------- FrameXML surface
ITEM_QUALITY_COLORS = {}
for i = -1, 6 do ITEM_QUALITY_COLORS[i] = { hex = string.format("|cffQ%d", i) } end
local QN = { [0]="Poor","Common","Uncommon","Rare","Epic","Legendary","Artifact","Heirloom" }
for q = 0, 7 do _G["ITEM_QUALITY" .. q .. "_DESC"] = QN[q] end
ITEM_LEVEL, ITEM_MIN_LEVEL = "Item Level %d", "Requires Level %d"
LEVEL_RANGE, USABLE_ITEMS, RESET = "Level Range", "Usable Items", "Reset"
RETRIEVING_ITEM_INFO, YES, NO = "Retrieving item information", "Yes", "No"
UIParent, UISpecialFrames, SlashCmdList, StaticPopupDialogs = widget("UIParent"), {}, {}, {}
DEFAULT_CHAT_FRAME = { AddMessage = function(_, m) note("chat:", m) end }
tinsert = table.insert
function StaticPopup_Show(...) note("popup", ...) return true end
function FauxScrollFrame_Update() end
function FauxScrollFrame_GetOffset() return 0 end
function FauxScrollFrame_SetOffset() end
function IsShiftKeyDown() return false end
function ChatEdit_InsertLink() return false end
function GetTime() return os.clock() end
function UnitName(u) return u == "player" and "Grishnak" or "Testee" end
function UnitExists(u) return TARGET ~= nil end
function UnitIsPlayer() return TARGET == "player" end
function UnitIsConnected() return true end
function UnitClass() return "Mage", "MAGE" end
function UnitRace() return "Human", "Human" end
function UnitLevel() return 80 end
function GetNumSkillLines() return 2 end
function GetSkillLineInfo(i)
    if i == 1 then return "Armor Proficiencies", true, true, 0 end
    return "Cloth", false, false, 1
end

-- item 6948 is "already cached", everything else is not: exactly the split the tooltip code
-- has to cope with.
CACHED = { [6948] = "|cffffffff|Hitem:6948:0:0:0:0:0:0:0:80:0|h[Hearthstone]|h|r" }
QUERIED = {}
function GetItemInfo(id)
    QUERIED[id] = (QUERIED[id] or 0) + 1
    local link = CACHED[id]
    if not link then return nil end
    return "Hearthstone", link, 1, 1, 1, "Miscellaneous", "Junk", 1, "", 134414
end

GameTooltip = widget("GameTooltip")
GameTooltip.lines = {}
function GameTooltip:SetOwner(o) self.owner = o; self.lines = {} end
function GameTooltip:IsOwned(o) return self.owner == o end
function GameTooltip:ClearLines() self.lines = {} end
function GameTooltip:AddLine(t) self.lines[#self.lines + 1] = tostring(t) end
function GameTooltip:AddDoubleLine(l, r) self.lines[#self.lines + 1] = tostring(l) .. " | " .. tostring(r) end
function GameTooltip:SetHyperlink(link) self.lines = { "HYPERLINK " .. tostring(link) } end
function GameTooltip:Show() end
function GameTooltip:Hide() self.owner = nil end

-- dropdown stubs that behave like the real ones in the two ways that matter: Initialize
-- calls the init function immediately, and AddButton falls back to info.text for the value.
DROPDOWN = {}
function UIDropDownMenu_CreateInfo() return {} end
function UIDropDownMenu_AddButton(info)
    local list = DROPDOWN[UIDropDownMenu_current] or {}
    DROPDOWN[UIDropDownMenu_current] = list
    local value = info.value
    if value == nil then value = info.text end
    list[#list + 1] = { text = info.text, value = value, func = info.func,
                        checked = info.checked }
end
function UIDropDownMenu_Initialize(frame, init)
    frame._init = init
    UIDropDownMenu_current = frame:GetName()
    DROPDOWN[UIDropDownMenu_current] = {}
    if init then init(frame) end
end
function UIDropDownMenu_SetWidth() end
function UIDropDownMenu_JustifyText() end
function UIDropDownMenu_SetText(f, t) f._ddtext = t end
function UIDropDownMenu_SetSelectedValue(f, v) f._ddvalue = v end
function UIDropDownMenu_EnableDropDown(f) f._ddenabled = true end
function UIDropDownMenu_DisableDropDown(f) f._ddenabled = false end

-- ---------------------------------------------------------------------------- load
local function run(path)
    local chunk, err = loadfile(path)
    if not chunk then error("load " .. path .. ": " .. tostring(err)) end
    chunk()
end
run(ADDON .. "/Data.lua")
run(ADDON .. "/Data/Icons.lua")
run(ADDON .. "/Data/Filters.lua")
for i = 1, 8 do run(string.format("%s/Data/Items_%02d.lua", ADDON, i)) end
run(ADDON .. "/Data/Meta.lua")
run(ADDON .. "/Search.lua")
run(ADDON .. "/Transport.lua")
run(ADDON .. "/UI.lua")

ItemBrowserTransport.mode = "chat"      -- no event loop here; skip the probe

local D = ItemBrowserData
local frame = _G["ItemBrowserFrame"]
local function W(n) return _G["ItemBrowserFrame" .. n] end

-- The XML calls these; do it by hand in the same order the client would.
ItemBrowser_ListOnLoad(W("List"))
ItemBrowser_OnLoad(frame)
ItemBrowser_OnEvent(frame, "ADDON_LOADED", "ItemBrowser")

print("== load and ADDON_LOADED")
check(W("Reset"):GetText() == "Reset", "Reset button labelled from the client's RESET string")
check(W("LevelMinLabel"):GetText() == "Level Range", "level box labelled from LEVEL_RANGE")
check(W("UsableText"):GetText() == "Usable Items", "checkbox labelled from USABLE_ITEMS")
check(W("Category")._ddtext == "All categories", "category dropdown starts on All")
check(W("SubCategory")._ddenabled == false, "subcategory dropdown starts disabled")
check(#DROPDOWN["ItemBrowserFrameCategory"] == 1 + #D.categoryOrder,
      "category menu has All + " .. #D.categoryOrder .. " categories")

-- OnShow, then pump frames until the scan settles.
local function pump(limit)
    local ticks = 0
    for _ = 1, limit or 200 do
        ItemBrowser_OnUpdate(frame, 0.25)
        ticks = ticks + 1
        if W("Status"):GetText():find("^%d") or W("Status"):GetText():find("^All") then break end
    end
    return ticks
end
frame:Show()
ItemBrowser_OnShow(frame)
local ticks = pump()
print("\n== first open")
check(W("Status"):GetText() == "All 46098 items.",
      "settles on the whole catalogue in " .. ticks .. " ticks: " .. W("Status"):GetText())
check(W("Row1Name"):GetText():find("Martin Fury") ~= nil,
      "row 1 is the first item by id: " .. tostring(W("Row1Name"):GetText()))
check(W("Row1Icon")._texture ~= nil and W("Row1Category"):GetText() ~= "",
      "row 1 has an icon and a category: " .. tostring(W("Row1Category"):GetText()))
check(W("Give")._enabled == false, "Give is disabled with nothing selected")
check(W("Selection"):GetText():find("nothing yet") ~= nil,
      "selection line says so: " .. W("Selection"):GetText())
check(W("Recipient"):GetText():find("yourself") and W("Recipient"):GetText():find("nothing targeted"),
      "recipient line names the fallback and why: " .. W("Recipient"):GetText())

print("\n== the filter bar")
local function clickMenu(dropdown, text)
    for _, entry in ipairs(DROPDOWN["ItemBrowserFrame" .. dropdown] or {}) do
        if entry.text:find(text, 1, true) then
            entry.func({ value = entry.value, GetText = function() return entry.text end })
            return true
        end
    end
    return false
end
check(clickMenu("Category", "Armor"), "picked Armor from the category menu")
pump()
check(W("Status"):GetText() == "23578 of 46098 items.", "-> " .. W("Status"):GetText())
check(W("SubCategory")._ddenabled == true and W("Category")._ddtext == "Armor",
      "subcategory enabled, category shows " .. tostring(W("Category")._ddtext))
UIDropDownMenu_Initialize(W("SubCategory"), W("SubCategory")._init)   -- as opening it would
check(clickMenu("SubCategory", "Plate"), "picked Plate from the subcategory menu")
pump()
check(W("Status"):GetText() == "4264 of 46098 items." and W("SubCategory")._ddtext == "Plate",
      "-> " .. W("Status"):GetText() .. " / " .. tostring(W("SubCategory")._ddtext))
check(clickMenu("Quality", "Epic"), "picked Epic or better")
pump()
check(W("Status"):GetText() == "1985 of 46098 items.", "-> " .. W("Status"):GetText())
W("LevelMin"):SetText("80"); ItemBrowser_FilterChanged()
W("LevelMax"):SetText("80"); ItemBrowser_FilterChanged()
pump()
check(W("Status"):GetText() == "1301 of 46098 items.", "+ required level 80..80 -> " .. W("Status"):GetText())
W("IlvlMin"):SetText("264"); ItemBrowser_FilterChanged()
pump()
local afterIlvl = W("Status"):GetText()
check(afterIlvl == "194 of 46098 items.", "+ item level 264+ -> " .. afterIlvl)
W("Search"):SetText("ymirjar"); ItemBrowser_SearchChanged(W("Search"))
pump()
check(W("Row1Name"):GetText():find("Ymirjar") ~= nil and W("Status"):GetText() == "21 of 46098 items.",
      "+ name \"ymirjar\" -> " .. tostring(W("Row1Name"):GetText()) .. " (" .. W("Status"):GetText() .. ")")
check(ItemBrowserSaved.levelMin == 80 and ItemBrowserSaved.ilvlMin == 264,
      "the numeric boxes were persisted to SavedVariables without waiting for OnHide")

print("\n== the Usable checkbox")
W("Search"):SetText(""); ItemBrowser_SearchChanged(W("Search"))
ItemBrowser_ResetFilters(); pump()
W("Usable"):SetChecked(true); ItemBrowser_FilterChanged(); pump()
local usableOnly = W("Status"):GetText()
check(usableOnly == "20826 of 46098 items.",
      "a level 80 human mage with cloth only sees " .. usableOnly)
check(ItemBrowserSaved.usable == true, "the checkbox is persisted")
local okU = pcall(ItemBrowser_UsableEnter, W("Usable"))
check(okU and table.concat(GameTooltip.lines, " "):find("auction house") ~= nil,
      "its tooltip explains what the test is and what it leaves out")
W("Usable"):SetChecked(false); ItemBrowser_FilterChanged(); pump()
local okG = pcall(ItemBrowser_GiveEnter, W("Give"))
check(okG and table.concat(GameTooltip.lines, " "):find("your own") ~= nil,
      "the Give button's tooltip names the recipient: " .. table.concat(GameTooltip.lines, " "))

-- back to the narrow filter the tooltip tests below expect
check(clickMenu("Category", "Armor"), "re-picked Armor")
UIDropDownMenu_Initialize(W("SubCategory"), W("SubCategory")._init)
clickMenu("SubCategory", "Plate")
clickMenu("Quality", "Epic")
W("LevelMin"):SetText("80"); W("LevelMax"):SetText("80"); W("IlvlMin"):SetText("264")
W("Search"):SetText("ymirjar"); ItemBrowser_SearchChanged(W("Search")); pump()

print("\n== tooltips")
local row = W("Row1")
ItemBrowser_RowEnter(row)
local uncachedLines = #GameTooltip.lines
check(GameTooltip.lines[1]:find("Ymirjar") ~= nil
      and table.concat(GameTooltip.lines, "\n"):find("Retrieving item information") ~= nil,
      "an uncached item draws the shipped summary + the client's retrieving string ("
      .. uncachedLines .. " lines)")
check(QUERIED[row.entry] and QUERIED[row.entry] > 0,
      "hovering queried the server for item " .. tostring(row.entry))
-- the server answers a moment later
CACHED[row.entry] = "|cffa335ee|Hitem:" .. row.entry .. ":0:0:0:0:0:0:0:80:0|h[x]|h|r"
ItemBrowser_OnUpdate(frame, 0.01)
check(GameTooltip.lines[1]:find("^HYPERLINK") ~= nil,
      "the poll swapped in the real tooltip in place: " .. GameTooltip.lines[1])
local footer = table.concat(GameTooltip.lines, " / ")
check(footer:find("Armor / Plate") ~= nil and footer:find("id " .. row.entry) ~= nil,
      "our footer is appended under the real tooltip: " .. footer:gsub("HYPERLINK[^/]*/ ", ""))
ItemBrowser_RowLeave()
-- prefetch: scrolling past rows must have queued queries without hovering them
local queried = 0
for _ in pairs(QUERIED) do queried = queried + 1 end
check(queried > 5, "prefetch asked the server about " .. queried .. " items it had drawn")

print("\n== selection and the give bar")
ItemBrowser_RowClick(row)
check(W("Give")._enabled == true and W("Give"):GetText() == "Give to me",
      "clicking a row enables the button: " .. W("Give"):GetText())
check(W("Selection"):GetText():find("Ymirjar") ~= nil,
      "selection line names the item: " .. W("Selection"):GetText())
W("Quantity"):SetText("5"); ItemBrowser_QuantityChanged()
check(W("Selection"):GetText():find("5x") ~= nil,
      "and the quantity: " .. W("Selection"):GetText())
TARGET = "player"
ItemBrowser_OnEvent(frame, "PLAYER_TARGET_CHANGED")
check(W("Give"):GetText() == "Give to Testee" and W("Recipient"):GetText():find("Testee"),
      "targeting a player renames the button: " .. W("Give"):GetText())
ItemBrowser_GiveClicked()
check(log[#log]:find("popup") ~= nil, "5x to someone else asks for confirmation")
TARGET = nil
ItemBrowser_OnEvent(frame, "PLAYER_TARGET_CHANGED")

print("\n== reset")
ItemBrowser_ResetFilters()
pump()
check(W("Status"):GetText() == "All 46098 items." and W("Search"):GetText() == ""
      and W("Category")._ddtext == "All categories" and W("LevelMin"):GetText() == "",
      "Reset clears every filter: " .. W("Status"):GetText())

print("\n== slash commands")
for _, cmd in ipairs({ "help", "status", "reset", "chat", "addon", "" , "linen" }) do
    local ok, err = pcall(SlashCmdList["ITEMBROWSER"], cmd)
    check(ok, string.format("/ib %-7s runs%s", cmd == "" and "(bare)" or cmd,
                            ok and "" or (": " .. tostring(err))))
end
pump()

print("\n== a filter that matches nothing")
W("Search"):SetText("qqqzzz"); ItemBrowser_SearchChanged(W("Search"))
pump(400)
check(W("Status"):GetText():find("Nothing matches") ~= nil, W("Status"):GetText())
check(W("Row1"):IsShown() == false, "and every row is hidden")


print(string.format("\n%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
