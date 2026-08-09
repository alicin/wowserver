--[[----------------------------------------------------------------------------------------
ItemBrowser self-test, part 2: the UI wiring.

    tools/selftest.sh                dump the rows and run both parts
    luajit tools/selftest-ui.lua     just this part

Drives UI.lua, Tree.lua and Launcher.lua for real against widget stubs: ADDON_LOADED, OnShow,
OnUpdate ticks until each scan settles, the category tree down all three tiers, the level
sliders and their one-click bands, the sort headings, row hover before and after the server
answers, row click, the give bar, resizing, Reset, a simulated /reload, and every slash
subcommand.

THE HEADLINE CASE IS THE USER'S OWN SENTENCE. "Bows between 10 and 15", done with nothing but
clicks: three tree clicks and four slider drags, with the name box asserted empty at the end.
Both readings of "10 and 15" are checked, because they are different items.

It cannot tell you the window LOOKS right -- nothing here measures a pixel. It tells you that
nothing in it indexes a nil, which is the failure that otherwise costs a trip in game.

The stubs simplify freely EXCEPT where copying the client is the whole point:
  * UIDropDownMenu_AddButton falls back to info.text when info.value is nil
    (UIDropDownMenu.lua:336-342). That is why menu entries need real values.
  * GetSkillLineInfo returns skillName, isHeader, isExpanded, skillRank in that order
    (FrameXML/SkillFrame.lua:26).
  * GameTooltip:SetHyperlink on a CACHED item produces a multi-line tooltip and on an
    uncached one produces a single "Retrieving item information" line. Both are simulated,
    because RealTooltip's line-count guard exists precisely for the second case.
------------------------------------------------------------------------------------------]]

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
                          _enabled = true, _scripts = {}, _points = {}, _height = 400,
                          _width = 500, _alpha = 1 }, Widget)
end
function Widget:GetName() return self._name end
function Widget:SetText(t)
    self._text = t
    -- The client fires OnTextChanged from SetText, and several handlers depend on that (the
    -- clear button, the slider that follows a box). Copying it keeps the guard flags honest.
    local handler = self._scripts.OnTextChanged
    if handler then handler(self) end
end
function Widget:GetText() return self._text end
function Widget:SetChecked(v) self._checked = v and true or false end
function Widget:GetChecked() return self._checked and 1 or nil end
function Widget:Show() self._shown = true end
function Widget:Hide() self._shown = false end
function Widget:IsShown() return self._shown end
function Widget:Enable() self._enabled = true end
function Widget:Disable() self._enabled = false end
function Widget:SetTexture(t) self._texture = t end
function Widget:SetTexCoord() end
function Widget:SetHighlightTexture() end
function Widget:SetAlpha(a) self._alpha = a end
function Widget:SetValue(v)
    v = tonumber(v) or 0
    self._value = v
    local handler = self._scripts.OnValueChanged
    if handler then handler(self, v) end
end
function Widget:GetValue() return self._value or 0 end
function Widget:SetMinMaxValues(lo, hi) self._min, self._max = lo, hi end
function Widget:GetMinMaxValues() return self._min or 0, self._max or 0 end
function Widget:SetValueStep() end
function Widget:SetFocus() end
function Widget:ClearFocus() end
function Widget:SetPoint() end
function Widget:GetPoint() return "CENTER", nil, "CENTER", 0, 0 end
function Widget:ClearAllPoints() end
function Widget:SetFrameLevel() end
function Widget:GetFrameLevel() return 1 end
function Widget:SetFrameStrata() end
function Widget:EnableMouseWheel() end
function Widget:EnableMouse() end
function Widget:RegisterForDrag() end
function Widget:RegisterEvent() end
function Widget:SetScript(k, f) self._scripts[k] = f end
function Widget:GetScript(k) return self._scripts[k] end
function Widget:StartMoving() end
function Widget:StartSizing() end
function Widget:StopMovingOrSizing() end
function Widget:SetMovable() end
function Widget:SetResizable() end
function Widget:SetMinResize() end
function Widget:SetMaxResize() end
function Widget:SetWidth(w) self._width = w end
function Widget:GetWidth() return self._width end
function Widget:SetHeight(h) self._height = h end
function Widget:GetHeight() return self._height end
function Widget:GetCenter() return 100, 100 end
function Widget:GetEffectiveScale() return 1 end
function Widget:LockHighlight() self._locked = true end
function Widget:UnlockHighlight() self._locked = false end
function Widget:SetJustifyH() end
function Widget:SetFontObject() end
function Widget:GetFontString() return self._fontstring end
function Widget:CreateTexture() return widget(nil) end
function Widget:CreateFontString() return widget(nil) end

-- Any ItemBrowser* / INVTYPE_* global is manufactured on demand, so the XML's widget tree
-- does not have to be transcribed. Everything else reads as nil, the way it would in game.
setmetatable(_G, { __index = function(t, k)
    if type(k) == "string" and k:find("^ItemBrowser") then
        local v = widget(k)
        rawset(t, k, v)
        return v
    end
    return nil
end })

-- The INVTYPE_* strings, copied verbatim from this client's own
-- Interface\\FrameXML\\GlobalStrings.lua. Not invented, and not manufactured by the
-- metatable above, because the duplicates are the point: CHEST and ROBE are both "Chest" and
-- SHIELD and WEAPONOFFHAND are both "Off Hand", which is what the tree has to collapse into
-- one row. A stub that returned the token name would hide exactly that behaviour.
INVTYPE_2HWEAPON, INVTYPE_AMMO, INVTYPE_BAG, INVTYPE_BODY = "Two-Hand", "Ammo", "Bag", "Shirt"
INVTYPE_CHEST, INVTYPE_CLOAK, INVTYPE_FEET, INVTYPE_FINGER = "Chest", "Back", "Feet", "Finger"
INVTYPE_HAND, INVTYPE_HEAD, INVTYPE_HOLDABLE = "Hands", "Head", "Held In Off-hand"
INVTYPE_LEGS, INVTYPE_NECK, INVTYPE_QUIVER = "Legs", "Neck", "Quiver"
INVTYPE_RANGED, INVTYPE_RANGEDRIGHT, INVTYPE_RELIC = "Ranged", "Ranged", "Relic"
INVTYPE_ROBE, INVTYPE_SHIELD, INVTYPE_SHOULDER = "Chest", "Off Hand", "Shoulder"
INVTYPE_TABARD, INVTYPE_THROWN, INVTYPE_TRINKET = "Tabard", "Thrown", "Trinket"
INVTYPE_WAIST, INVTYPE_WEAPON, INVTYPE_WEAPONMAINHAND = "Waist", "One-Hand", "Main Hand"
INVTYPE_WEAPONOFFHAND, INVTYPE_WRIST = "Off Hand", "Wrist"

CREATED = {}
function CreateFrame(_, name, _, _)
    local f = widget(name)
    f._fontstring = widget(name and (name .. "Text"))
    if name then rawset(_G, name, f); CREATED[name] = f end
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
Minimap = widget("Minimap")
DEFAULT_CHAT_FRAME = { AddMessage = function(_, m) note("chat:", m) end }
tinsert = table.insert
function StaticPopup_Show(...) note("popup", ...) return true end
function GetCursorPosition() return 140, 60 end

-- FauxScrollFrame, reduced to the two things the addon actually uses: it remembers an offset
-- and it reports it back.
SCROLL_OFFSET = {}
function FauxScrollFrame_Update(frame, items, display, height)
    frame._items, frame._display = items, display
end
function FauxScrollFrame_GetOffset(frame) return SCROLL_OFFSET[frame:GetName()] or 0 end
function FauxScrollFrame_SetOffset(frame, o) SCROLL_OFFSET[frame:GetName()] = o end
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
-- has to cope with. RENDER_LINES says how many lines the client would draw for a cached item;
-- setting it to 1 simulates the "Retrieving item information" tooltip that a half-cached
-- item produces, which is what RealTooltip's line-count guard is for.
CACHED = { [6948] = "|cffffffff|Hitem:6948:0:0:0:0:0:0:0:80:0|h[Hearthstone]|h|r" }
QUERIED = {}
RENDER_LINES = 6
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
function GameTooltip:NumLines() return #self.lines end
function GameTooltip:AddLine(t) self.lines[#self.lines + 1] = tostring(t) end
function GameTooltip:AddDoubleLine(l, r)
    self.lines[#self.lines + 1] = tostring(l) .. " | " .. tostring(r)
end
function GameTooltip:SetHyperlink(link)
    self.lines = { "HYPERLINK " .. tostring(link) }
    for i = 2, RENDER_LINES do
        self.lines[i] = "clientline" .. i        -- stats, sockets, set bonuses, flavour...
    end
end
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
run(ADDON .. "/Tree.lua")
run(ADDON .. "/Launcher.lua")

ItemBrowserTransport.mode = "chat"      -- no event loop here; skip the probe

local D = ItemBrowserData
local frame = _G["ItemBrowserFrame"]
local function W(n) return _G["ItemBrowserFrame" .. n] end

-- The XML calls these; do it by hand in the same order the client would.
ItemBrowser_ListOnLoad(W("List"))
ItemBrowserTree_OnLoad(W("Tree"))
for _, slider in ipairs({ "ReqMinSlider", "ReqMaxSlider", "IlvlMinSlider", "IlvlMaxSlider" }) do
    ItemBrowser_RangeSliderLoad(W(slider))
    -- The XML wires this; the stub's SetValue then fires it, so a test that drags a slider
    -- goes through exactly the path a mouse does.
    W(slider):SetScript("OnValueChanged", ItemBrowser_RangeSliderChanged)
end
-- The rest of the XML's script wiring.
W("Search"):SetScript("OnTextChanged", ItemBrowser_SearchChanged)
W("Quantity"):SetScript("OnTextChanged", ItemBrowser_QuantityChanged)
for _, box in ipairs({ "LevelMin", "LevelMax", "IlvlMin", "IlvlMax" }) do
    W(box):SetScript("OnTextChanged", ItemBrowser_RangeBoxChanged)
end
ItemBrowser_OnLoad(frame)
ItemBrowser_OnEvent(frame, "ADDON_LOADED", "ItemBrowser")

print("== load and ADDON_LOADED")
check(W("Reset"):GetText() == "Reset", "Reset button labelled from the client's RESET string")
check(W("LevelMinLabel"):GetText() == "Requires Level",
      "the required-level range is labelled from ITEM_MIN_LEVEL: "
      .. W("LevelMinLabel"):GetText())
check(W("IlvlMinLabel"):GetText() == "Item Level",
      "the item-level range is labelled from ITEM_LEVEL: " .. W("IlvlMinLabel"):GetText())
check(W("UsableText"):GetText() == "Usable Items", "checkbox labelled from USABLE_ITEMS")
check(select(2, W("ReqMinSlider"):GetMinMaxValues()) == D.limits.reqLevel
      and select(2, W("IlvlMaxSlider"):GetMinMaxValues()) == D.limits.itemLevel,
      string.format("sliders span the generated maxima: required 0-%d, item level 0-%d",
                    D.limits.reqLevel, D.limits.itemLevel))
check(#DROPDOWN["ItemBrowserFrameSort"] == #ItemBrowserSearch.orders,
      "the sort menu offers all " .. #ItemBrowserSearch.orders .. " orders")
check(_G["ItemBrowserMinimapButton"] ~= nil and _G["ItemBrowserMinimapButton"]:IsShown(),
      "the minimap button exists and is visible")
check(type(BINDING_NAME_ITEMBROWSER_TOGGLE) == "string",
      "the keybinding is named for the Key Bindings panel: " ..
      tostring(BINDING_NAME_ITEMBROWSER_TOGGLE))

-- OnShow, then pump frames until the scan settles.
local function pump(limit)
    for _ = 1, limit or 300 do
        ItemBrowser_OnUpdate(frame, 0.25)
        local text = W("Status"):GetText()
        if text:find("^%d") or text:find("^All") or text:find("Nothing matches") then break end
    end
    return W("Status"):GetText()
end
frame:Show()
ItemBrowser_OnShow(frame)

print("\n== first open")
check(pump():find("^All 46098 items") ~= nil, "settles on the whole catalogue: " .. pump())
check(W("Row1Name"):GetText():find("Martin Fury") ~= nil,
      "row 1 is the first item by id: " .. tostring(W("Row1Name"):GetText()))
check(W("Row1Icon")._texture ~= nil and W("Row1Id"):GetText() == "17",
      "row 1 has an icon and its id: " .. tostring(W("Row1Id"):GetText()))
local rowCount = 0
while _G["ItemBrowserFrameRow" .. (rowCount + 1)] and CREATED["ItemBrowserFrameRow" .. (rowCount + 1)] do
    rowCount = rowCount + 1
end
check(rowCount == 14, "the row pool sized itself to the window: " .. rowCount ..
      " rows for a 400px list at 28px each")
check(W("Give")._enabled == false, "Give is disabled with nothing selected")
check(W("Recipient"):GetText():find("yourself") and W("Recipient"):GetText():find("nothing targeted"),
      "recipient line names the fallback and why: " .. W("Recipient"):GetText())

-- ------------------------------------------------------------------ the headline case
print("\n== \"bows between 10 and 15\", using nothing but the mouse")

local function treeNode(label)
    for i = 1, 60 do
        local button = _G["ItemBrowserFrameTreeNode" .. i]
        if button and CREATED["ItemBrowserFrameTreeNode" .. i] and button:IsShown()
           and button.node and button.node.label == label then
            return button
        end
    end
    return nil
end
local function clickTree(label)
    local button = treeNode(label)
    if not button then return false end
    ItemBrowserTree_NodeClick(button)
    return true
end

check(treeNode("All items") ~= nil and treeNode("Weapon") ~= nil,
      "the tree opens on All items + every category")
check(clickTree("Weapon"), "clicked Weapon in the tree")
check(pump() == "6651 of 46098 items.", "-> " .. pump())
check(treeNode("Bows") ~= nil, "Weapon expanded to its subcategories, including Bows")
check(clickTree("Bows"), "clicked Bows")
check(pump() == "308 of 46098 items.", "-> " .. pump())
check(treeNode("Ranged") ~= nil,
      "Bows expanded to its one real slot, which the client calls \"Ranged\"")

-- the item-level reading
W("IlvlMinSlider"):SetValue(10)
W("IlvlMaxSlider"):SetValue(15)
check(pump() == "10 of 46098 items.", "item level 10-15 by slider -> " .. pump())
check(W("IlvlMin"):GetText() == "10" and W("IlvlMax"):GetText() == "15",
      "the boxes followed the sliders: " .. W("IlvlMin"):GetText() .. " to " ..
      W("IlvlMax"):GetText())
check(string.find(string.lower(W("Row1Name"):GetText()), "bow", 1, true) ~= nil,
      "row 1 is a bow: " .. W("Row1Name"):GetText())
check(W("Search"):GetText() == "", "and the name box was never touched")

-- the required-level reading
ItemBrowser_ClearRange("ilvl")
W("ReqMinSlider"):SetValue(10)
W("ReqMaxSlider"):SetValue(15)
check(pump() == "6 of 46098 items.", "required level 10-15 by slider -> " .. pump())
check(ItemBrowserSaved.levelMin == 10 and ItemBrowserSaved.levelMax == 15
      and ItemBrowserSaved.ilvlMin == nil,
      "the two ranges are stored separately and only one is set")

print("\n== the level bands")
local function preset(key, label)
    for i = 1, 12 do
        local button = _G["ItemBrowserFrame" .. key .. "Preset" .. i]
        if button and CREATED[button:GetName()] and button:GetText() == label then return button end
    end
end
local band = preset("req", "10-20")
check(band ~= nil, "the required-level row offers a 10-20 band")
band:GetScript("OnClick")(band)
check(ItemBrowserSaved.levelMin == 10 and ItemBrowserSaved.levelMax == 20
      and W("LevelMax"):GetText() == "20",
      "one click sets both ends and both boxes: " .. W("LevelMin"):GetText() .. "-" ..
      W("LevelMax"):GetText())
check(band._locked == true, "and the band highlights itself as the active one")
local any = preset("req", "Any")
any:GetScript("OnClick")(any)
check(ItemBrowserSaved.levelMin == nil and W("LevelMin"):GetText() == "",
      "the Any band clears the range")
check(pump() == "308 of 46098 items.", "back to all bows: " .. pump())

print("\n== the slot tier")
check(clickTree("Bows"), "collapsed Bows again")
check(clickTree("Weapon"), "collapsed Weapon")
check(clickTree("Armor") and pump() == "23578 of 46098 items.", "Armor -> " .. pump())
check(clickTree("Cloth") and pump() == "5721 of 46098 items.", "Armor / Cloth -> " .. pump())
check(clickTree("Head") and pump() == "590 of 46098 items.", "Armor / Cloth / Head -> " .. pump())
local slots = ItemBrowserTree_SelectedSlots()
check(slots and slots[1] == true, "the filter is a slot SET, holding INVTYPE_HEAD")
check(clickTree("Chest"), "picked Chest instead")
slots = ItemBrowserTree_SelectedSlots()
local chestIds = 0
for _ in pairs(slots or {}) do chestIds = chestIds + 1 end
check(chestIds == 2 and slots[5] and slots[20],
      "\"Chest\" is ONE row filtering on both ids the client calls Chest (5 and 20)")
check(tonumber(pump():match("^(%d+)")) > 590,
      "and it matches more than Head alone: " .. pump())

print("\n== quality and usable still work")
local function clickMenu(dropdown, text)
    for _, entry in ipairs(DROPDOWN["ItemBrowserFrame" .. dropdown] or {}) do
        if entry.text:find(text, 1, true) then
            entry.func({ value = entry.value, GetText = function() return entry.text end })
            return true
        end
    end
    return false
end
local beforeQuality = tonumber(pump():match("^(%d+)"))
check(clickMenu("Quality", "Epic"), "picked Epic or better")
local epicOnly = tonumber(pump():match("^(%d+)"))
check(epicOnly and epicOnly < beforeQuality,
      string.format("-> %d of the %d chest pieces are epic or better", epicOnly, beforeQuality))
check(clickMenu("Quality", "Any quality"), "back to any quality")
pump()

print("\n== sorting")
ItemBrowser_SortHeaderClick(W("HeadersLevel"))
check(pump():find("by item level, highest first") ~= nil,
      "clicking the ilvl heading sorts by it, best first: " .. pump())
local function rowIlvl(n) return tonumber(W("Row" .. n .. "Level"):GetText()) or 0 end
check(rowIlvl(1) >= rowIlvl(2) and rowIlvl(2) >= rowIlvl(3),
      string.format("rows descend by item level: %d, %d, %d", rowIlvl(1), rowIlvl(2), rowIlvl(3)))
ItemBrowser_SortHeaderClick(W("HeadersLevel"))
pump()
check(rowIlvl(1) <= rowIlvl(2), "clicking it again reverses: " .. rowIlvl(1) .. ", " .. rowIlvl(2))
check(W("HeadersLevelArrow"):IsShown() and not W("HeadersIdArrow"):IsShown(),
      "the arrow is on the sorted column and nowhere else")
check(clickMenu("Sort", "Name"), "picked Name from the sort menu")
pump()
check(W("Sort")._ddvalue == "name", "the menu and the headings share one setting")
check(clickMenu("Sort", "Best match"), "back to best match")
pump()

print("\n== reset, then the tooltip cases")
ItemBrowser_ResetFilters()
pump()
check(pump():find("^All 46098") ~= nil and ItemBrowserSaved.class == nil
      and W("IlvlMin"):GetText() == "" and treeNode("All items")._locked ~= false,
      "Reset clears the tree, both ranges and the name box: " .. pump())

-- narrow to something small so row 1 is a known uncached item
check(clickTree("Weapon") and clickTree("Bows"), "Weapon / Bows again")
pump()
local row = W("Row1")
ItemBrowser_RowEnter(row)
check(GameTooltip.lines[1]:find("|r") ~= nil
      and table.concat(GameTooltip.lines, "\n"):find("Retrieving item information") ~= nil,
      "an uncached item draws the shipped summary + the client's retrieving string ("
      .. #GameTooltip.lines .. " lines)")
check(QUERIED[row.entry] and QUERIED[row.entry] > 0,
      "hovering queried the server for item " .. tostring(row.entry))
check(table.concat(GameTooltip.lines, " "):find("Slot | Ranged") ~= nil,
      "the fallback names the slot in the client's own words")

-- the server answers a moment later
CACHED[row.entry] = "|cffa335ee|Hitem:" .. row.entry .. ":0:0:0:0:0:0:0:80:0|h[x]|h|r"
ItemBrowser_OnUpdate(frame, 0.01)
check(GameTooltip.lines[1]:find("^HYPERLINK") ~= nil,
      "the poll swapped in the real tooltip in place: " .. GameTooltip.lines[1])
local footer = table.concat(GameTooltip.lines, " / ")
check(footer:find("Weapon / Bows") ~= nil and footer:find("id " .. row.entry) ~= nil,
      "our footer is appended under the real tooltip")
ItemBrowser_RowLeave()

-- and the failure this addon is supposed to survive: a cache entry that renders one line
RENDER_LINES = 1
local row2 = W("Row2")
CACHED[row2.entry] = "|cffffffff|Hitem:" .. row2.entry .. ":0:0:0:0:0:0:0:80:0|h[y]|h|r"
ItemBrowser_RowEnter(row2)
check(table.concat(GameTooltip.lines, "\n"):find("Retrieving item information") ~= nil,
      "a cached item whose tooltip renders one line falls back rather than showing a stub")
RENDER_LINES = 6
ItemBrowser_RowLeave()

-- prefetch: scrolling past rows must have queued queries without hovering them
local queried = 0
for _ in pairs(QUERIED) do queried = queried + 1 end
check(queried > 5, "prefetch asked the server about " .. queried .. " items it had drawn")

print("\n== selection and the give bar")
ItemBrowser_RowClick(row)
check(W("Give")._enabled == true and W("Give"):GetText() == "Give to me",
      "clicking a row enables the button: " .. W("Give"):GetText())
check(W("Selection"):GetText():find("|r") ~= nil,
      "selection line names the item: " .. W("Selection"):GetText())
local up = W("QuantityUp")
for _ = 1, 4 do ItemBrowser_QuantityStep(up) end
check(W("Quantity"):GetText() == "5", "the + stepper counts up without typing: "
      .. W("Quantity"):GetText())
ItemBrowser_QuantityChanged()
check(W("Selection"):GetText():find("5x") ~= nil,
      "and the selection line says how many: " .. W("Selection"):GetText())
local down = W("QuantityDown")
for _ = 1, 10 do ItemBrowser_QuantityStep(down) end
check(W("Quantity"):GetText() == "1", "the - stepper stops at 1, not at zero or below")
ItemBrowser_QuantityChanged()
W("Quantity"):SetText("5"); ItemBrowser_QuantityChanged()
TARGET = "player"
ItemBrowser_OnEvent(frame, "PLAYER_TARGET_CHANGED")
check(W("Give"):GetText() == "Give to Testee" and W("Recipient"):GetText():find("Testee"),
      "targeting a player renames the button: " .. W("Give"):GetText())
ItemBrowser_GiveClicked()
check(log[#log]:find("popup") ~= nil, "5x to someone else asks for confirmation")
TARGET = nil
ItemBrowser_OnEvent(frame, "PLAYER_TARGET_CHANGED")

print("\n== resizing")
W("ListScroll"):SetHeight(700)
W("TreeScroll"):SetHeight(700)
ItemBrowser_OnSizeChanged(frame)
local grown = 0
while CREATED["ItemBrowserFrameRow" .. (grown + 1)] do grown = grown + 1 end
check(grown == 25, "a taller window grows the row pool to " .. grown .. " and reuses the rest")
W("ListScroll"):SetHeight(400)
W("TreeScroll"):SetHeight(400)
ItemBrowser_OnSizeChanged(frame)
local after = 0
while CREATED["ItemBrowserFrameRow" .. (after + 1)] do after = after + 1 end
check(after == grown, "shrinking it back hides rows instead of destroying them: still "
      .. after .. " created")
ItemBrowser_StopSizing()
check(ItemBrowserSaved.size ~= nil and ItemBrowserSaved.size.width ~= nil,
      "the size is written to SavedVariables")

print("\n== a simulated /reload restores the filters")
ItemBrowserSaved.class, ItemBrowserSaved.subclass = 2, 2
ItemBrowserSaved.slotKey = "Ranged"
ItemBrowserSaved.ilvlMin, ItemBrowserSaved.ilvlMax = 10, 15
ItemBrowserSaved.minQuality = 2
ItemBrowser_OnEvent(frame, "ADDON_LOADED", "ItemBrowser")
ItemBrowser_OnShow(frame)
-- 7 is what the database says:
--   SELECT COUNT(*) FROM item_template WHERE class=2 AND subclass=2
--     AND InventoryType IN (15,26) AND ItemLevel BETWEEN 10 AND 15 AND Quality>=2;
check(pump() == "7 of 46098 items.",
      "the saved bows/Ranged/ilvl 10-15/uncommon+ filter comes back by itself: " .. pump())
check(W("IlvlMin"):GetText() == "10" and W("IlvlMaxSlider"):GetValue() == 15
      and treeNode("Ranged") ~= nil,
      "boxes, sliders and the expanded tree all agree with the saved state")
ItemBrowser_ResetFilters()
pump()

print("\n== slash commands")
for _, cmd in ipairs({ "help", "status", "reset", "minimap", "minimap", "chat", "addon",
                       "", "linen" }) do
    local ok, err = pcall(SlashCmdList["ITEMBROWSER"], cmd)
    check(ok, string.format("/ib %-7s runs%s", cmd == "" and "(bare)" or cmd,
                            ok and "" or (": " .. tostring(err))))
end
check(_G["ItemBrowserMinimapButton"]:IsShown(),
      "two /ib minimap calls leave the button where it started")
frame:Show()
pump()

print("\n== a filter that matches nothing")
W("Search"):SetText("qqqzzz"); ItemBrowser_SearchChanged(W("Search"))
pump(400)
check(W("Status"):GetText():find("Nothing matches") ~= nil, W("Status"):GetText())
check(W("Row1"):IsShown() == false, "and every row is hidden")
check(W("SearchClear"):IsShown(), "the clear button appeared with the text")
ItemBrowser_ClearSearch()
check(W("SearchClear"):IsShown() == false, "and went away with it")


print(string.format("\n%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
