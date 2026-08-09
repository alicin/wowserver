--[[----------------------------------------------------------------------------------------
ItemBrowser -- behaviour.

Layout lives in UI.xml and the category tree in Tree.lua. This file is the wiring: the filter
bar, the two level ranges, the budgeted search loop, the recycled result rows, the sort
headers, tooltips, and the one button that hands an item over.

NOTHING HERE NEEDS THE KEYBOARD
===============================
Every filter can be set with the mouse alone, because "bows between 10 and 15" should not
require knowing how to spell either word:

  * the CATEGORY TREE (Tree.lua) is the auction house's own three tiers -- class, subclass,
    inventory slot -- built from the generated Data/Filters.lua, which counted them off the
    live item_template. Weapon -> Bows exists because 308 rows say so.
  * each LEVEL RANGE has three ways in and they are all the same state: a row of one-click
    bands (1-10, 10-20, ...), a slider per end for exact values, and a box you can type in.
    Drag, click a band, roll the wheel over a slider, or type -- whatever you touch, the
    other two follow.
  * QUALITY and USABLE are a dropdown and a tick, as in the auction house.
  * SORT is a menu and a row of clickable column headings, which are the same setting.

The two ranges are labelled with the CLIENT's own strings for them -- "Requires Level" and
"Item Level", lifted out of ITEM_MIN_LEVEL and ITEM_LEVEL -- because "level" alone means two
different numbers and a browser that guesses which one you meant is worse than one that asks.

THE TOOLTIP RULE, because it is the least obvious thing here.
=============================================================
A real item tooltip -- stats, sockets, set bonuses, procs, use effects, flavour text, the red
"Requires Level" line -- can only be drawn by the CLIENT, from item data the client holds. An
addon cannot fake it and should not try; the shipped database has the name, the icon and six
numbers, and that is all it will ever have.

On a 3.3.5a client that data arrives from the server on demand. Touching GetItemInfo() for an
item the client has never seen returns nil AND makes the client send CMSG_ITEM_QUERY_SINGLE;
the SMSG_ITEM_QUERY_SINGLE_RESPONSE lands a moment later and goes into itemcache.wdb, and from
then on the client can draw that item forever, across sessions. So there are three parts:

  1. PREFETCH. Every time the list is re-filled, the ids now on screen are queued. A few
     queries per PREFETCH_INTERVAL are issued from that queue -- rate limited, and each id
     asked at most once per session -- so an item you have merely scrolled past is usually
     already cached by the time you hover it.
  2. HOVER. GameTooltip:SetHyperlink(link) once GetItemInfo() has an answer: the genuine
     tooltip, identical to hovering the item in a bag, plus our own id/category footer.
  3. WAIT. Otherwise draw a summary from the shipped database, mark it with the client's own
     RETRIEVING_ITEM_INFO string, and keep polling GetItemInfo for TOOLTIP_WAIT seconds. The
     instant it resolves, the tooltip is replaced in place under the still-hovering cursor.

WHY THE GATE IS GetItemInfo AND NOT SetHyperlink ITSELF. SetHyperlink("item:49623") on an
uncached item does not fail: it draws a one-line tooltip that says "Retrieving item
information", which looks like a bug and tells you nothing. GetItemInfo returning a name is
the only reliable "the client has this item" test available in 3.3.5, so it decides which of
the two tooltips gets drawn. RealTooltip additionally checks that the tooltip came out with
more than one line, because a cache entry can exist and still be useless.

Polling is not laziness: 3.3.5 has no event for this. GET_ITEM_INFO_RECEIVED does not exist
until Mists, and there is no callback form of GetItemInfo. Polling one id per frame for six
seconds is the whole available API.

FAILURE MODES.
  * The server never answers -- mid-loading-screen, dropped reply, an id the server's
    item_template does not have. The summary is what you keep, the poll gives up after
    TOOLTIP_WAIT, and moving the cursor away and back retries.
  * Worse because it is silent: itemcache.wdb is keyed by item id alone and is NOT per-realm,
    so a client that has played on a server with a differently edited item 49623 answers
    instantly with that other server's data. Nothing an addon can detect. Deleting the
    client's Cache/ directory is the fix.
------------------------------------------------------------------------------------------]]

local D = ItemBrowserData
local S = ItemBrowserSearch

local ROW_HEIGHT = 28        -- must match the OnVerticalScroll step in UI.xml
local MIN_ROWS = 4
local MAX_ROWS = 40          -- ~1100px of list; the pool never grows past this
local SEARCH_DELAY = 0.20    -- seconds of no typing before the search is started
local SCAN_BUDGET = 6000     -- rows of filtering per frame; ~2-3 ms, see Search.lua
local IDLE_BUDGET = 3000     -- rows of lowercase-index priming per idle frame
local TOOLTIP_WAIT = 6       -- seconds to keep waiting for the server's item data
local PREFETCH_INTERVAL = 0.2
local PREFETCH_PER_TICK = 4  -- => at most 20 item queries a second while scrolling
local MAX_QUANTITY = 1000
local MIN_WIDTH, MIN_HEIGHT = 780, 520
local MAX_WIDTH, MAX_HEIGHT = 1800, 1400

local rows = {}
local visibleRows = 0
local results, shown, matchedCount, cappedResults = {}, 0, 0, false
local searchNote = nil
local searchDirty = false
local sinceType = 0
local scanning = false
local updating = false       -- re-entrancy guard: FauxScrollFrame_Update can re-enter us
local settingFilters = false -- suppress change handlers while widgets are refilled
local selectedEntry = nil
local pendingTooltip = nil   -- { row, entry, expires }
local pendingGive = nil      -- captured before the confirmation popup, used after it

local prefetchQueue, prefetchSeen, sincePrefetch = {}, {}, 0

ItemBrowserSaved = ItemBrowserSaved or {}

local ANY_QUALITY = "Any quality"


-- =========================================================================================
-- small helpers
-- =========================================================================================

local function Widget(name)
    return _G["ItemBrowserFrame" .. name]
end
ItemBrowser_Widget = Widget          -- Tree.lua and Launcher.lua use the same lookup

--- "Item Level %d" -> "Item Level". Used to label the two ranges with the client's own
--- words for them, in the client's own locale, rather than with English typed here.
local function StripFormat(text, fallback)
    if type(text) ~= "string" or text == "" then return fallback end
    local stripped = string.gsub(text, "%s*%%%d?%$?[ds]", "")
    stripped = string.gsub(stripped, ":%s*$", "")
    if stripped == "" then return fallback end
    return stripped
end

-- The feedback line inherits a grey font, which is right for "sending..." and wrong for the
-- two outcomes that matter, so those are coloured explicitly.
local function Feedback(text, tone)
    local fs = Widget("Feedback")
    if not fs then return end
    if tone == "error" then
        fs:SetText("|cffff6060" .. text .. "|r")
    elseif tone == "ok" then
        fs:SetText("|cff40ff40" .. text .. "|r")
    else
        fs:SetText(text)
    end
end

local function Quantity()
    local box = Widget("Quantity")
    local n = tonumber(box and box:GetText() or "") or 1
    n = math.floor(n)
    if n < 1 then n = 1 end
    if n > MAX_QUANTITY then n = MAX_QUANTITY end
    return n
end


-- =========================================================================================
-- the two level ranges
-- =========================================================================================
--
-- One piece of state per bound, in SavedVariables, and three views of it. nil means "no
-- bound", which is NOT the same as zero: an item with RequiredLevel 0 is most items.
--
-- The slider encodes "no bound" as its own extreme -- 0 for a minimum, the database's maximum
-- for a maximum -- which is why the sliders are built from D.limits (generated from the live
-- table) rather than from a hardcoded 1..80. A realm whose item_template reaches ilvl 435
-- gets a slider that reaches 435.

local RANGE = {
    req = {
        savedMin = "levelMin", savedMax = "levelMax",
        boxMin = "LevelMin", boxMax = "LevelMax",
        sliderMin = "ReqMinSlider", sliderMax = "ReqMaxSlider",
        anyButton = "ReqAny",
        limitKey = "reqLevel", fallbackLimit = 100,
        presetsY = -38,
        presets = {
            { "Any" }, { "1-10", 1, 10 }, { "10-20", 10, 20 }, { "20-30", 20, 30 },
            { "30-40", 30, 40 }, { "40-50", 40, 50 }, { "50-60", 50, 60 },
            { "60-70", 60, 70 }, { "70-80", 70, 80 }, { "80+", 80 },
        },
    },
    ilvl = {
        savedMin = "ilvlMin", savedMax = "ilvlMax",
        boxMin = "IlvlMin", boxMax = "IlvlMax",
        sliderMin = "IlvlMinSlider", sliderMax = "IlvlMaxSlider",
        anyButton = "IlvlAny",
        limitKey = "itemLevel", fallbackLimit = 300,
        presetsY = -104,
        presets = {
            { "Any" }, { "1-30", 1, 30 }, { "30-60", 30, 60 }, { "60-100", 60, 100 },
            { "100-150", 100, 150 }, { "150-200", 150, 200 }, { "200-232", 200, 232 },
            { "232-264", 232, 264 }, { "264+", 264 },
        },
    },
}

-- Which range and which end every slider and every box belongs to. Filled in at load from
-- the RANGE table above, so a widget can find its own meaning from its own name.
local ROLE = {}
for key, range in pairs(RANGE) do
    ROLE["ItemBrowserFrame" .. range.sliderMin] = { range = key, bound = "min" }
    ROLE["ItemBrowserFrame" .. range.sliderMax] = { range = key, bound = "max" }
    ROLE["ItemBrowserFrame" .. range.boxMin] = { range = key, bound = "min" }
    ROLE["ItemBrowserFrame" .. range.boxMax] = { range = key, bound = "max" }
end

local function RangeLimit(key)
    local range = RANGE[key]
    return (D.limits and D.limits[range.limitKey]) or range.fallbackLimit
end

local function RangeValue(key, bound)
    local range = RANGE[key]
    return ItemBrowserSaved[bound == "min" and range.savedMin or range.savedMax]
end

--- Push the stored bounds into the box, the slider and the preset highlights.
local function PushRangeWidgets(key)
    local range = RANGE[key]
    local limit = RangeLimit(key)
    local minValue, maxValue = RangeValue(key, "min"), RangeValue(key, "max")
    local wasSetting = settingFilters
    settingFilters = true

    local box = Widget(range.boxMin)
    if box then box:SetText(minValue and tostring(minValue) or "") end
    box = Widget(range.boxMax)
    if box then box:SetText(maxValue and tostring(maxValue) or "") end

    local slider = Widget(range.sliderMin)
    if slider then slider:SetValue(minValue or 0) end
    slider = Widget(range.sliderMax)
    if slider then slider:SetValue(maxValue or limit) end

    for i = 1, #(range.buttons or {}) do
        local button = range.buttons[i]
        if button.presetMin == minValue and button.presetMax == maxValue then
            button:LockHighlight()
        else
            button:UnlockHighlight()
        end
    end

    settingFilters = wasSetting
end

--- The one way a bound ever changes.
-- Keeps min <= max by dragging the other end along rather than by refusing the input: a range
-- that silently ignores half of what you do with it feels broken.
local function SetRangeValue(key, bound, value)
    local range = RANGE[key]
    local limit = RangeLimit(key)
    if value then
        value = math.floor(value)
        if value < 0 then value = 0 end
        if value > limit then value = limit end
    end
    local saved = ItemBrowserSaved
    if bound == "min" then
        if value == 0 then value = nil end      -- a minimum of zero excludes nothing
        saved[range.savedMin] = value
        if value and saved[range.savedMax] and saved[range.savedMax] < value then
            saved[range.savedMax] = value
        end
    else
        if value == limit then value = nil end  -- a maximum at the top excludes nothing
        saved[range.savedMax] = value
        if value and saved[range.savedMin] and saved[range.savedMin] > value then
            saved[range.savedMin] = value
        end
    end
    PushRangeWidgets(key)
end

function ItemBrowser_RangeSliderLoad(self)
    local role = ROLE[self:GetName() or ""]
    if not role then return end
    local limit = RangeLimit(role.range)
    self:SetMinMaxValues(0, limit)
    self:SetValueStep(1)
    self:SetValue(role.bound == "min" and 0 or limit)
    self:EnableMouseWheel(true)
    -- OptionsSliderTemplate's three captions are all blanked: the edit box beside the slider
    -- already shows the number and the bounds are in the tooltip, so drawing them again
    -- would cost twenty vertical pixels for nothing.
    local name = self:GetName()
    for _, suffix in ipairs({ "Text", "Low", "High" }) do
        local fs = _G[name .. suffix]
        if fs then fs:SetText("") end
    end
end

function ItemBrowser_RangeSliderChanged(self, value)
    if settingFilters then return end
    local role = ROLE[self:GetName() or ""]
    if not role then return end
    -- 3.3.5 has no SetObeyStepOnDrag, so a dragged slider reports fractions.
    SetRangeValue(role.range, role.bound, math.floor(value + 0.5))
    ItemBrowser_FilterChanged()
end

function ItemBrowser_RangeSliderWheel(self, delta)
    local role = ROLE[self:GetName() or ""]
    if not role then return end
    self:SetValue(self:GetValue() + delta)
end

function ItemBrowser_RangeBoxChanged(self)
    if settingFilters then return end
    local role = ROLE[self:GetName() or ""]
    if not role then return end
    local text = self:GetText()
    local value = tonumber(text)
    if text ~= "" and not value then return end
    -- Typing into the box must not fight the box: the value is stored and pushed back to the
    -- slider, but the box's own text is left exactly as typed until focus moves on.
    local range = RANGE[role.range]
    local saved = ItemBrowserSaved
    if value then
        value = math.floor(value)
        if value < 0 then value = 0 end
        local limit = RangeLimit(role.range)
        if value > limit then value = limit end
    end
    saved[role.bound == "min" and range.savedMin or range.savedMax] = value
    local wasSetting = settingFilters
    settingFilters = true
    local slider = Widget(role.bound == "min" and range.sliderMin or range.sliderMax)
    if slider then
        slider:SetValue(value or (role.bound == "min" and 0 or RangeLimit(role.range)))
    end
    settingFilters = wasSetting
    ItemBrowser_FilterChanged()
end

function ItemBrowser_ClearRange(key)
    local range = RANGE[key]
    ItemBrowserSaved[range.savedMin] = nil
    ItemBrowserSaved[range.savedMax] = nil
    PushRangeWidgets(key)
    ItemBrowser_FilterChangedNow()
end

local function RangeLabel(key)
    if key == "req" then
        return StripFormat(ITEM_MIN_LEVEL, "Requires Level")
    end
    return StripFormat(ITEM_LEVEL, "Item Level")
end

local function RangeExplain(key)
    if key == "req" then
        return "The level a character has to BE before they can equip or use the item.\n\n" ..
               "A level 12 hunter looking for a bow they can use right now wants this one."
    end
    return "The item's own power rating, which is not the level you need to use it.\n\n" ..
           "Two items requiring level 80 can be item level 200 and item level 284."
end

local function RangeTooltip(owner, key, extra)
    GameTooltip:SetOwner(owner, "ANCHOR_RIGHT")
    GameTooltip:ClearLines()
    GameTooltip:AddLine(RangeLabel(key))
    GameTooltip:AddLine(RangeExplain(key), 1, 1, 1, true)
    GameTooltip:AddLine(" ")
    GameTooltip:AddDoubleLine("Range in this database",
                              "0 - " .. RangeLimit(key), 0.7, 0.7, 0.7, 1, 1, 1)
    if extra then GameTooltip:AddLine(extra, 0.7, 0.7, 0.7, true) end
    GameTooltip:Show()
end

function ItemBrowser_RangeSliderEnter(self)
    local role = ROLE[self:GetName() or ""]
    if not role then return end
    RangeTooltip(self, role.range,
                 (role.bound == "min" and "Lowest" or "Highest") ..
                 " accepted value. Drag it, or roll the mouse wheel over it, one step at a " ..
                 "time. Dragging it to the end means \"no limit\".")
end

function ItemBrowser_ClearRangeEnter(self, key)
    RangeTooltip(self, key, "Clears both ends of this range.")
end

local function PresetClicked(self)
    -- Both ends at once, straight into the stored state: a band is a statement about the
    -- whole range, so pushing it through SetRangeValue one end at a time would let the
    -- min<=max clamp fight the second half of the click.
    local range = RANGE[self.rangeKey]
    ItemBrowserSaved[range.savedMin] = self.presetMin
    ItemBrowserSaved[range.savedMax] = self.presetMax
    PushRangeWidgets(self.rangeKey)
    ItemBrowser_FilterChangedNow()
end

local function PresetEnter(self)
    RangeTooltip(self, self.rangeKey,
                 self.presetMin and ("Sets this range to " .. self.presetMin .. " - " ..
                                     (self.presetMax or "no limit") .. ".")
                 or "Clears this range.")
end

--- Build the one-click bands under each range. In Lua rather than in XML because they are a
--- table of numbers, and nineteen near-identical <Button> blocks would be a table of numbers
--- written the long way.
local function BuildPresets(frame)
    local box = Widget("Levels")
    for key, range in pairs(RANGE) do
        range.buttons = {}
        local previous = nil
        for i = 1, #range.presets do
            local preset = range.presets[i]
            local button = CreateFrame("Button",
                                       "ItemBrowserFrame" .. key .. "Preset" .. i,
                                       frame, "UIPanelButtonTemplate")
            button:SetHeight(18)
            button:SetWidth(preset[2] and 48 or 40)
            button:SetText(preset[1])
            local text = button.GetFontString and button:GetFontString()
            if text then text:SetFontObject(GameFontNormalSmall) end
            if previous then
                button:SetPoint("LEFT", previous, "RIGHT", 2, 0)
            else
                button:SetPoint("TOPLEFT", box, "TOPLEFT", 12, range.presetsY)
            end
            button.rangeKey = key
            button.presetMin, button.presetMax = preset[2], preset[3]
            button:SetScript("OnClick", PresetClicked)
            button:SetScript("OnEnter", PresetEnter)
            button:SetScript("OnLeave", function() GameTooltip:Hide() end)
            range.buttons[i] = button
            previous = button
        end
    end
end


-- =========================================================================================
-- who gets the item
-- =========================================================================================

--- @return name, isSelf, warning
local function Recipient()
    local me = UnitName("player")
    if UnitExists("target") then
        if UnitIsPlayer("target") and UnitIsConnected("target") then
            local name = UnitName("target")
            if name and name ~= "" and name ~= me then
                return name, false, nil
            end
            if name == me then
                return me, true, nil
            end
        end
        return me, true, "your target is not a player"
    end
    return me, true, "nothing targeted"
end

--- The whole point of the bottom bar: WHAT is about to be given, and to WHOM.
-- Both are spelled out in two lines and again on the button, because "Give" next to a list of
-- 46,000 items and an invisible target selection is the one place this addon can quietly do
-- the wrong thing.
local function UpdateGiveBar()
    local name, isSelf, warning = Recipient()

    local recipient = Widget("Recipient")
    if recipient then
        if isSelf then
            local suffix = warning and ("  |cffffd100(" .. warning .. ")|r") or ""
            recipient:SetText("Recipient:  |cffffffffyourself|r" .. suffix)
        else
            recipient:SetText("Recipient:  |cff40ff40" .. name .. "|r")
        end
    end

    local selection = Widget("Selection")
    local index = selectedEntry and D:Find(selectedEntry) or nil
    if selection then
        if index then
            local quantity = Quantity()
            local count = quantity > 1 and (quantity .. "x  ") or ""
            selection:SetText("Selected:  " .. count .. (D:ColouredName(index)) ..
                              "  |cff808080(" .. selectedEntry .. ")|r")
        else
            selection:SetText("|cff808080Selected:  nothing yet -- click a row|r")
        end
    end

    local give = Widget("Give")
    if give then
        -- Button:SetEnabled does not exist on 3.3.5; Enable/Disable is the pair this client
        -- has (see UIPanelTemplates.lua's own tab handling).
        give:SetText(isSelf and "Give to me" or ("Give to " .. name))
        if index then give:Enable() else give:Disable() end
    end
end

function ItemBrowser_QuantityChanged()
    ItemBrowserSaved.quantity = Quantity()
    UpdateGiveBar()
end

function ItemBrowser_QuantityStep(self)
    local step = self.step or 1
    local box = Widget("Quantity")
    if not box then return end
    local value = Quantity() + step
    if value < 1 then value = 1 end
    if value > MAX_QUANTITY then value = MAX_QUANTITY end
    box:SetText(tostring(value))
end


-- =========================================================================================
-- reading the filter bar
-- =========================================================================================

local function CurrentFilter()
    local saved = ItemBrowserSaved
    local box = Widget("Search")
    return {
        text         = box and box:GetText() or "",
        class        = saved.class,
        subclass     = saved.subclass,
        slots        = ItemBrowserTree_SelectedSlots(),
        minQuality   = saved.minQuality or 0,
        minLevel     = saved.levelMin,
        maxLevel     = saved.levelMax,
        minItemLevel = saved.ilvlMin,
        maxItemLevel = saved.ilvlMax,
        usable       = Widget("Usable") and Widget("Usable"):GetChecked() and true or false,
        sort         = saved.sort,
        sortDesc     = saved.sortDesc,
    }
end

local function StartSearch()
    searchDirty = false
    local filter = CurrentFilter()
    -- Persist here rather than in OnHide: a client that is closed, or /reload-ed, with the
    -- window still open never fires OnHide, and losing the filters you just set to a crash is
    -- a small betrayal. Everything else already writes straight to ItemBrowserSaved.
    ItemBrowserSaved.usable = filter.usable

    S:Begin(filter)
    scanning = true
    -- One large slice straight away. Anything that only touches a few thousand rows -- which
    -- is most searches once a category is chosen -- finishes here and never shows a progress
    -- line at all.
    if S:Step(SCAN_BUDGET * 2) then
        ItemBrowser_FinishSearch()
    else
        ItemBrowser_UpdateList()
    end
end

function ItemBrowser_FilterChanged()
    if settingFilters then return end
    searchDirty = true
    sinceType = 0
end

--- Same thing without the typing delay. A click on a category, a band or a sort heading is a
--- decision, not a half-finished word, so it re-runs on the next frame instead of waiting
--- SEARCH_DELAY for a keystroke that is not coming.
function ItemBrowser_FilterChangedNow()
    ItemBrowser_FilterChanged()
    sinceType = SEARCH_DELAY
end


-- =========================================================================================
-- results list
-- =========================================================================================

--- Ask the client for an item it may not have. Cheap and idempotent from our side: the id is
-- remembered so it is only ever queried once, and the queue is drained a few at a time so
-- flicking the scroll wheel down 46,000 rows cannot turn into 46,000 packets in one frame.
local function Prefetch(entry)
    if prefetchSeen[entry] then return end
    prefetchSeen[entry] = true
    prefetchQueue[#prefetchQueue + 1] = entry
end

local function DrainPrefetch()
    local n = #prefetchQueue
    if n == 0 then return end
    local take = n > PREFETCH_PER_TICK and PREFETCH_PER_TICK or n
    for i = 1, take do
        -- The call IS the request. GetItemInfo on an unknown id returns nil and sends
        -- CMSG_ITEM_QUERY_SINGLE; the return value is genuinely not wanted here.
        GetItemInfo(prefetchQueue[i])
    end
    for i = 1, n - take do
        prefetchQueue[i] = prefetchQueue[i + take]
    end
    for i = n - take + 1, n do
        prefetchQueue[i] = nil
    end
end

--- What the "Slot" column says: the equipment slot for anything equippable, and the
--- subcategory for everything else, so the column is never blank and never useless.
local function RowType(class, subclass, invType)
    local slot = D:SlotLabel(invType)
    if slot then return slot end
    local _, subLabel = D:CategoryLabel(class, subclass)
    return subLabel or ""
end

function ItemBrowser_UpdateList()
    if updating then return end
    updating = true

    local scroll = Widget("ListScroll")
    FauxScrollFrame_Update(scroll, shown, visibleRows, ROW_HEIGHT)
    -- FauxScrollFrame_GetOffset just returns frame.offset (UIPanelTemplates.lua:245-247),
    -- and nothing sets that field until the first OnVerticalScroll. The window can be
    -- filled before it has ever been scrolled, so the fallback is not paranoia.
    local offset = FauxScrollFrame_GetOffset(scroll) or 0

    for i = 1, #rows do
        local row = rows[i]
        local index = (i <= visibleRows and offset + i <= shown) and results[offset + i] or nil
        if index then
            local entry = D.entry[index]
            local _, invType, class, subclass, reqLevel, itemLevel = D:Decode(index)
            row.index = index
            row.entry = entry
            local name = row:GetName()
            _G[name .. "Icon"]:SetTexture(D:IconPath(index))
            _G[name .. "Name"]:SetText((D:ColouredName(index)))
            _G[name .. "Slot"]:SetText(RowType(class, subclass, invType))
            _G[name .. "Req"]:SetText(reqLevel > 0 and tostring(reqLevel) or "")
            _G[name .. "Level"]:SetText(itemLevel > 0 and tostring(itemLevel) or "")
            _G[name .. "Id"]:SetText(tostring(entry))
            if selectedEntry == entry then
                _G[name .. "Selected"]:Show()
            else
                _G[name .. "Selected"]:Hide()
            end
            row:Show()
            Prefetch(entry)
        else
            row.index = nil
            row.entry = nil
            row:Hide()
        end
    end

    ItemBrowser_UpdateStatus()
    updating = false
end

--- The sort suffix on the status line, so the order is never a mystery.
local function SortSuffix()
    local order = S:Order(ItemBrowserSaved.sort)
    if order.key == "match" then return "" end
    return "  |cff808080-- by " .. string.lower(order.label) ..
           (ItemBrowserSaved.sortDesc and ", highest first" or ", lowest first") .. "|r"
end

function ItemBrowser_UpdateStatus()
    local status = Widget("Status")
    if not status then return end
    if scanning then
        status:SetText(string.format("|cffffd100Filtering %d%%...|r", S:Progress() * 100))
    elseif searchNote then
        status:SetText("|cffffd100" .. searchNote .. "|r")
    elseif matchedCount == 0 then
        status:SetText("|cffffd100Nothing matches these filters.|r  " ..
                       "|cff808080Widen a level range, or press Reset.|r")
    elseif cappedResults then
        -- "Best" is only true of the relevance order; under any other order these are simply
        -- the first MAX_RANKED the scan found, and saying otherwise would be a small lie.
        local kept = (S:Order(ItemBrowserSaved.sort).key == "match") and "the best" or "the first"
        status:SetText(string.format("%d matches, showing %s %d. Narrow it down.",
                                     matchedCount, kept, shown) .. SortSuffix())
    elseif matchedCount == D.rows then
        status:SetText(string.format("All %d items.", matchedCount) .. SortSuffix())
    else
        status:SetText(string.format("%d of %d items.", matchedCount, D.rows) .. SortSuffix())
    end
end

function ItemBrowser_FinishSearch()
    scanning = false
    results, shown, matchedCount, cappedResults, searchNote = S:Results()
    FauxScrollFrame_SetOffset(Widget("ListScroll"), 0)
    local bar = _G["ItemBrowserFrameListScrollScrollBar"]
    if bar then bar:SetValue(0) end
    ItemBrowser_UpdateList()
end

function ItemBrowser_SearchChanged(self)
    local hint = _G[self:GetName() .. "Hint"]
    local empty = self:GetText() == ""
    if hint then
        if empty then hint:Show() else hint:Hide() end
    end
    local clear = Widget("SearchClear")
    if clear then
        if empty then clear:Hide() else clear:Show() end
    end
    ItemBrowser_FilterChanged()
end

function ItemBrowser_ClearSearch()
    local box = Widget("Search")
    box:SetText("")
    box:ClearFocus()
end

--- Grow the row pool to `count` rows and lay them out. Called at load and on every resize;
--- rows are only ever created, never destroyed, because a frame cannot be destroyed in this
--- API and re-hiding one costs nothing.
local function EnsureRows(count)
    if count > MAX_ROWS then count = MAX_ROWS end
    if count < MIN_ROWS then count = MIN_ROWS end
    local list = Widget("List")
    local scroll = Widget("ListScroll")
    for i = #rows + 1, count do
        local row = CreateFrame("Button", "ItemBrowserFrameRow" .. i, list,
                                "ItemBrowserRowTemplate")
        row:SetHeight(ROW_HEIGHT)
        if i == 1 then
            row:SetPoint("TOPLEFT", scroll, "TOPLEFT", 0, 0)
            row:SetPoint("TOPRIGHT", scroll, "TOPRIGHT", 0, 0)
        else
            row:SetPoint("TOPLEFT", rows[i - 1], "BOTTOMLEFT", 0, 0)
            row:SetPoint("TOPRIGHT", rows[i - 1], "BOTTOMRIGHT", 0, 0)
        end
        -- Rows and the scroll frame are siblings, so they default to the same frame level
        -- and the winner of a mouse hit is decided by creation order. Being explicit means
        -- the rows keep their clicks and tooltips no matter what order things load in.
        row:SetFrameLevel(scroll:GetFrameLevel() + 2)
        _G[row:GetName() .. "Selected"]:Hide()
        row:Hide()
        rows[i] = row
    end
    visibleRows = count
end

function ItemBrowser_ListOnLoad(self)
    -- No enableMouseWheel attribute exists in the 3.3.5 UI schema, so it is set here. The
    -- rows sit on top of this frame and do not take wheel events themselves, and an
    -- unhandled wheel walks up the parent chain, so one handler here covers the whole list.
    self:EnableMouseWheel(true)
    FauxScrollFrame_SetOffset(_G[self:GetName() .. "Scroll"], 0)
    EnsureRows(MIN_ROWS)
end

function ItemBrowser_ListOnMouseWheel(self, delta)
    local scroll = _G[self:GetName() .. "Scroll"]
    local bar = _G[scroll:GetName() .. "ScrollBar"]
    local step = ROW_HEIGHT * 3
    bar:SetValue(bar:GetValue() - delta * step)
end


-- =========================================================================================
-- sorting
-- =========================================================================================

-- Column heading -> the order it selects. The Slot column sorts by inventory type, which is
-- head-to-relic order, the same order the character pane lays its slots out in.
local SORT_HEADERS = {
    Name = "name", Slot = "slot", Req = "req", Level = "ilvl", Id = "id",
}

-- Which way round a column starts when you first click it. Numbers people want biggest-first
-- (the best gear, the highest level); names they want A-Z.
local SORT_DEFAULT_DESC = {
    name = false, slot = false, id = false, ilvl = true, req = true, quality = true,
}

local function ApplySortState()
    local saved = ItemBrowserSaved
    local active = S:Order(saved.sort)
    for suffix, key in pairs(SORT_HEADERS) do
        local button = Widget("Headers" .. suffix)
        if button then
            local arrow = _G[button:GetName() .. "Arrow"]
            if arrow then
                if active.key == key then
                    -- One arrow texture, flipped through its TexCoords for the other
                    -- direction. The stock UI does exactly this (SortButton_UpdateArrow).
                    if saved.sortDesc then
                        arrow:SetTexCoord(0, 0.5625, 1, 0)
                    else
                        arrow:SetTexCoord(0, 0.5625, 0, 1)
                    end
                    arrow:Show()
                else
                    arrow:Hide()
                end
            end
        end
    end
    local dropdown = Widget("Sort")
    if dropdown then
        -- The menu names the order and nothing else. Which way round it is goes in the arrow
        -- on the column heading and in words on the status line -- not in a triangle glyph
        -- here, because 3.3.5's fonts are not guaranteed to have one and a missing glyph
        -- draws as a box.
        UIDropDownMenu_SetSelectedValue(dropdown, active.key)
        UIDropDownMenu_SetText(dropdown, active.label)
    end
end

local function SetSort(key, desc)
    ItemBrowserSaved.sort = key
    ItemBrowserSaved.sortDesc = desc and true or false
    ApplySortState()
    ItemBrowser_FilterChanged()
    sinceType = SEARCH_DELAY        -- a sort is a decision, not typing: re-run at once
end

function ItemBrowser_SortHeaderClick(self)
    local suffix = string.gsub(self:GetName(), "^ItemBrowserFrameHeaders", "")
    local key = SORT_HEADERS[suffix]
    if not key then return end
    if ItemBrowserSaved.sort == key then
        SetSort(key, not ItemBrowserSaved.sortDesc)
    else
        SetSort(key, SORT_DEFAULT_DESC[key])
    end
end

function ItemBrowser_SortHeaderEnter(self)
    local suffix = string.gsub(self:GetName(), "^ItemBrowserFrameHeaders", "")
    local key = SORT_HEADERS[suffix]
    if not key then return end
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    GameTooltip:ClearLines()
    GameTooltip:AddLine("Sort by " .. string.lower(S:Order(key).label))
    if ItemBrowserSaved.sort == key then
        GameTooltip:AddLine("Click to reverse the order.", 1, 1, 1)
    else
        GameTooltip:AddLine("Click once to sort, again to reverse.", 1, 1, 1)
    end
    GameTooltip:Show()
end

local function SortSelected(self)
    local key = self.value
    SetSort(key, SORT_DEFAULT_DESC[key])
end

local function SortDropDown_Initialize()
    local saved = ItemBrowserSaved
    local orders = S.orders
    for i = 1, #orders do
        local info = UIDropDownMenu_CreateInfo()
        info.text = orders[i].label
        info.value = orders[i].key
        info.func = SortSelected
        info.checked = (S:Order(saved.sort).key == orders[i].key)
        UIDropDownMenu_AddButton(info)
    end
end


-- =========================================================================================
-- tooltips
-- =========================================================================================

--- The lines this addon adds under any tooltip, real or fallback.
local function TooltipFooter(index, entry)
    local _, invType, class, subclass = D:Decode(index)
    local classLabel, subLabel = D:CategoryLabel(class, subclass)
    GameTooltip:AddLine(" ")
    if classLabel then
        GameTooltip:AddDoubleLine(classLabel .. (subLabel and (" / " .. subLabel) or ""),
                                  "id " .. entry, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6)
    else
        GameTooltip:AddDoubleLine(" ", "id " .. entry, 0, 0, 0, 0.6, 0.6, 0.6)
    end
    local slot = D:SlotLabel(invType)
    if slot then
        GameTooltip:AddDoubleLine("Slot", slot, 0.6, 0.6, 0.6, 0.9, 0.9, 0.9)
    end
    GameTooltip:AddLine("Click to select" ..
                        (selectedEntry == entry and " (selected)" or "") ..
                        ", shift-click to link it in chat.", 0.5, 0.5, 0.5, true)
end

--- Everything the shipped database knows, drawn like a tooltip. Only ever seen for the second
--- or two before the server answers -- and permanently if it never does.
local function FallbackTooltip(index, entry)
    local _, _, _, _, reqLevel, itemLevel = D:Decode(index)
    local coloured, _, quality = D:ColouredName(index)

    GameTooltip:AddLine(coloured)
    GameTooltip:AddLine(D:ColouredQualityName(quality))
    if itemLevel > 0 then
        GameTooltip:AddLine(string.format(ITEM_LEVEL, itemLevel), 1, 1, 1)
    end
    if reqLevel > 0 then
        GameTooltip:AddLine(string.format(ITEM_MIN_LEVEL, reqLevel), 1, 1, 1)
    end
    TooltipFooter(index, entry)
    GameTooltip:AddLine(" ")
    GameTooltip:AddLine("|cff808080" .. (RETRIEVING_ITEM_INFO or "Retrieving item information")
                        .. "|r")
end

--- Try to draw the client's own tooltip. Returns false if the client does not have the item.
local function RealTooltip(index, entry)
    -- Touching GetItemInfo is what makes the client ask the server for this item, so this
    -- call is doing real work even on the branch where it returns nil. Its NAME is the gate:
    -- a name back means this id is in itemcache.wdb and every other field, including the
    -- link, is therefore available too.
    local name, link = GetItemInfo(entry)
    if not name then return false end
    -- The link carries the item's default suffix and enchant fields; "item:<id>" alone is
    -- equivalent for a plain item and is what we fall back to if the client hands back a
    -- name without a link.
    link = link or ("item:" .. entry)
    GameTooltip:ClearLines()
    -- The genuine article: stats, sockets and their bonus, set membership and set bonuses,
    -- procs ("Chance on hit"), use effects, durability, flavour text, "Requires Level" in red
    -- when it is too high. None of that is in item_template in a form an addon could
    -- re-render, and all of it is in the client.
    GameTooltip:SetHyperlink(link)
    -- Belt and braces: a cache entry can exist and still produce nothing useful (a truncated
    -- wdb record, an id the server answered for with an empty template). One line means the
    -- client drew "Retrieving item information" or nothing at all, and the shipped summary is
    -- better than either.
    if GameTooltip.NumLines and GameTooltip:NumLines() <= 1 then
        GameTooltip:ClearLines()
        return false
    end
    TooltipFooter(index, entry)
    GameTooltip:Show()
    return true
end

function ItemBrowser_RowEnter(row)
    local index = row.index
    if not index then return end
    local entry = row.entry

    GameTooltip:SetOwner(row, "ANCHOR_RIGHT")
    GameTooltip:ClearLines()

    if RealTooltip(index, entry) then
        pendingTooltip = nil
    else
        FallbackTooltip(index, entry)
        GameTooltip:Show()
        pendingTooltip = { row = row, index = index, entry = entry,
                           expires = GetTime() + TOOLTIP_WAIT }
    end
end

function ItemBrowser_RowLeave()
    pendingTooltip = nil
    GameTooltip:Hide()
end

function ItemBrowser_UsableEnter(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:ClearLines()
    GameTooltip:AddLine(USABLE_ITEMS or "Usable Items")
    GameTooltip:AddLine("Only items this character could equip or use: class, race, required "
                        .. "level, weapon and armour proficiency, and required skill.",
                        1, 1, 1, true)
    GameTooltip:AddLine(" ")
    GameTooltip:AddLine("Same test the auction house runs, minus its required-spell check -- "
                        .. "3.3.5 gives an addon no way to ask whether you know a given spell.",
                        0.7, 0.7, 0.7, true)
    GameTooltip:Show()
end

function ItemBrowser_ResetEnter(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:ClearLines()
    GameTooltip:AddLine("Clear every filter")
    GameTooltip:AddLine("Category, slot, quality, both level ranges, the name box and the " ..
                        "Usable tick. The sort order and the window's size and position stay.",
                        1, 1, 1, true)
    GameTooltip:Show()
end

function ItemBrowser_GiveEnter(self)
    local name, isSelf = Recipient()
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:ClearLines()
    if isSelf then
        GameTooltip:AddLine("Puts the item in |cffffffffyour own|r bags.")
        GameTooltip:AddLine("Target a player to give it to them instead.", 0.7, 0.7, 0.7, true)
    else
        GameTooltip:AddLine("Puts the item in |cff40ff40" .. name .. "|r's bags.")
        GameTooltip:AddLine("They are your current target.", 0.7, 0.7, 0.7, true)
    end
    GameTooltip:Show()
end


-- =========================================================================================
-- selection and giving
-- =========================================================================================

function ItemBrowser_RowClick(row)
    if not row.entry then return end

    -- Shift-click drops the item link into an open chat box, the same gesture as shift-
    -- clicking a bag slot. Only possible once the client actually has the item, which is
    -- why it is a bonus rather than the main path.
    if IsShiftKeyDown() then
        local _, link = GetItemInfo(row.entry)
        if link and ChatEdit_InsertLink(link) then return end
    end

    selectedEntry = row.entry
    Feedback("")
    UpdateGiveBar()
    ItemBrowser_UpdateList()
end

local function DoGive()
    local give = pendingGive
    pendingGive = nil
    if not give then return end
    Feedback("Sending...")
    ItemBrowserTransport:AddItem(give.target, give.entry, give.quantity, function(ok, text)
        if ok == true then
            Feedback(string.format("Gave %dx to %s.", give.quantity, give.target), "ok")
        elseif ok == false then
            Feedback(text or "The server refused the command.", "error")
        else
            Feedback(text or "Sent.")
        end
    end)
end

StaticPopupDialogs["ITEMBROWSER_CONFIRM_GIVE"] = {
    text = "Give %s to %s?",
    button1 = YES,
    button2 = NO,
    OnAccept = function() DoGive() end,
    OnCancel = function() pendingGive = nil end,
    timeout = 30,
    whileDead = 1,
    hideOnEscape = 1,
    showAlert = 1,
}

function ItemBrowser_GiveClicked()
    local index = selectedEntry and D:Find(selectedEntry) or nil
    if not index then
        Feedback("Click an item in the list first.", "error")
        return
    end

    local entry = D.entry[index]
    local quantity = Quantity()
    local target, isSelf = Recipient()
    local coloured = D:ColouredName(index)
    local label = (quantity > 1) and (quantity .. "x " .. coloured) or coloured

    pendingGive = { target = target, entry = entry, quantity = quantity }

    -- Confirm anything that is not "one of these, for me". Handing a stranger the wrong
    -- item, or a hundred of the right one, is the mistake worth a click to avoid; quietly
    -- giving yourself a single item is not.
    if isSelf and quantity == 1 then
        DoGive()
    elseif not StaticPopup_Show("ITEMBROWSER_CONFIRM_GIVE", label,
                                isSelf and "yourself" or ("|cff40ff40" .. target .. "|r")) then
        -- StaticPopup_Show returns nil when every popup slot is occupied. Saying so beats a
        -- Give button that looks like it did nothing.
        pendingGive = nil
        Feedback("Could not open the confirmation dialog; dismiss another popup first.", "error")
    end
end


-- =========================================================================================
-- the quality menu
-- =========================================================================================

local function QualityLabel(q)
    if not q or q == 0 then return ANY_QUALITY end
    return D:ColouredQualityName(q) .. "|cffffffff+|r"
end

local function QualitySelected(self)
    ItemBrowserSaved.minQuality = self.value
    UIDropDownMenu_SetSelectedValue(Widget("Quality"), self.value)
    UIDropDownMenu_SetText(Widget("Quality"), QualityLabel(self.value))
    ItemBrowser_FilterChangedNow()
end

local function QualityDropDown_Initialize()
    local current = ItemBrowserSaved.minQuality or 0
    for q = 0, 7 do
        local info = UIDropDownMenu_CreateInfo()
        info.text = (q == 0) and ANY_QUALITY
                    or (D:ColouredQualityName(q) .. " or better")
        info.value = q
        info.func = QualitySelected
        info.checked = (q == current)
        UIDropDownMenu_AddButton(info)
    end
end


-- =========================================================================================
-- filter state in and out of the widgets
-- =========================================================================================

--- Push the saved filter state into every widget. Guarded, because setting an EditBox's text
--- or a Slider's value fires the change handlers, which would otherwise queue a search per
--- widget on every login.
local function ApplyFilterWidgets()
    settingFilters = true
    local saved = ItemBrowserSaved
    Widget("Usable"):SetChecked(saved.usable and true or false)
    -- A saved class that no longer exists (the world DB changed under us) is dropped rather
    -- than left to index a nil category later.
    if saved.class and not D.category[saved.class] then
        saved.class, saved.subclass, saved.slotKey = nil, nil, nil
    end
    UIDropDownMenu_SetSelectedValue(Widget("Quality"), saved.minQuality or 0)
    UIDropDownMenu_SetText(Widget("Quality"), QualityLabel(saved.minQuality))
    settingFilters = false

    PushRangeWidgets("req")
    PushRangeWidgets("ilvl")
    ApplySortState()
    ItemBrowserTree_Refresh()

    local search = Widget("Search")
    ItemBrowser_SearchChanged(search)
end

function ItemBrowser_ResetFilters()
    local saved = ItemBrowserSaved
    saved.class, saved.subclass, saved.slotKey, saved.minQuality = nil, nil, nil, 0
    saved.levelMin, saved.levelMax, saved.ilvlMin, saved.ilvlMax = nil, nil, nil, nil
    saved.usable = false
    settingFilters = true
    Widget("Search"):SetText("")
    settingFilters = false
    ItemBrowserTree_Collapse()
    ApplyFilterWidgets()
    searchDirty = true
    sinceType = SEARCH_DELAY
end


-- =========================================================================================
-- frame lifecycle
-- =========================================================================================

local function RestorePosition(frame)
    local pos = ItemBrowserSaved.position
    if pos and pos.point then
        frame:ClearAllPoints()
        frame:SetPoint(pos.point, UIParent, pos.relPoint or pos.point, pos.x or 0, pos.y or 0)
    end
    local size = ItemBrowserSaved.size
    if size and size.width and size.height then
        local width = size.width
        local height = size.height
        if width < MIN_WIDTH then width = MIN_WIDTH end
        if height < MIN_HEIGHT then height = MIN_HEIGHT end
        if width > MAX_WIDTH then width = MAX_WIDTH end
        if height > MAX_HEIGHT then height = MAX_HEIGHT end
        frame:SetWidth(width)
        frame:SetHeight(height)
    end
end

function ItemBrowser_StopMoving(frame)
    frame:StopMovingOrSizing()
    local point, _, relPoint, x, y = frame:GetPoint()
    -- Only the anchor is saved, never the frame object GetPoint hands back: that would keep
    -- a reference to UIParent alive in the SavedVariables file, which cannot be serialised.
    ItemBrowserSaved.position = { point = point, relPoint = relPoint, x = x, y = y }
end

function ItemBrowser_StartSizing()
    ItemBrowserFrame:StartSizing("BOTTOMRIGHT")
end

function ItemBrowser_StopSizing()
    local frame = ItemBrowserFrame
    frame:StopMovingOrSizing()
    ItemBrowserSaved.size = { width = frame:GetWidth(), height = frame:GetHeight() }
    ItemBrowser_StopMoving(frame)   -- sizing from a corner moves the anchor too
end

--- Resizing changes how many rows fit, and nothing else. Both lists recompute their pool and
--- redraw; the filter bar is anchored, so it looks after itself.
function ItemBrowser_OnSizeChanged(frame)
    local scroll = Widget("ListScroll")
    if not scroll then return end             -- fires once before the children exist
    local fit = math.floor((scroll:GetHeight() or 0) / ROW_HEIGHT)
    if fit ~= visibleRows then
        EnsureRows(fit)
        ItemBrowser_UpdateList()
    end
    ItemBrowserTree_Resized()
end

function ItemBrowser_Toggle()
    local frame = ItemBrowserFrame
    if frame:IsShown() then frame:Hide() else frame:Show() end
end

function ItemBrowser_OnLoad(frame)
    frame:RegisterForDrag("LeftButton")
    frame:RegisterEvent("ADDON_LOADED")
    frame:RegisterEvent("PLAYER_TARGET_CHANGED")
    frame:SetMinResize(MIN_WIDTH, MIN_HEIGHT)
    frame:SetMaxResize(MAX_WIDTH, MAX_HEIGHT)
    tinsert(UISpecialFrames, frame:GetName())      -- Escape closes it

    -- Keybinding labels. Bindings.xml is picked up by the client automatically from the
    -- addon folder; these two globals are what the Key Bindings panel shows for it.
    BINDING_HEADER_ITEMBROWSER = "Item Browser"
    BINDING_NAME_ITEMBROWSER_TOGGLE = "Open / close the browser"

    local function Say(text)
        DEFAULT_CHAT_FRAME:AddMessage("|cff40c0ffItemBrowser|r " .. text)
    end

    SlashCmdList["ITEMBROWSER"] = function(msg)
        msg = string.gsub(msg or "", "^%s*(.-)%s*$", "%1")

        if msg == "" then
            ItemBrowser_Toggle()
        elseif msg == "help" then
            Say("/ib              toggle the window")
            Say("/ib <text>       open and search for <text>")
            Say("/ib reset        clear every filter")
            Say("/ib minimap      show or hide the minimap button")
            Say("/ib status       database and transport information")
            Say("/ib chat|addon   force a command transport (see Transport.lua)")
            Say("keybind: Key Bindings -> Item Browser, or drag the minimap button")
        elseif msg == "status" then
            local build = D.build
            Say("database: " .. (build and string.format(
                    "%d items, %d icons, %d shards, digest %s",
                    build.rows, build.icons, build.shards, build.digest)
                or "NOT LOADED, the generated Data/ files are missing"))
            Say("categories: " .. #D.categoryOrder .. ", restriction pool: " ..
                (#D.restrict / 4))
            Say("transport: " .. ItemBrowserTransport:Describe())
        elseif msg == "reset" then
            frame:Show()
            ItemBrowser_ResetFilters()
        elseif msg == "minimap" then
            Say(ItemBrowserLauncher_Toggle() and "minimap button shown"
                                             or "minimap button hidden")
        elseif msg == "chat" or msg == "addon" then
            -- Manual override. The addon channel is the better path but it is also the one
            -- that depends on the server build; if it ever misbehaves this is the way out
            -- without reinstalling anything.
            ItemBrowserTransport.mode = msg
            Say("transport forced to: " .. ItemBrowserTransport:Describe())
        else
            frame:Show()
            Widget("Search"):SetText(msg)
            Widget("Search"):SetFocus()
        end
    end
    SLASH_ITEMBROWSER1 = "/ib"
    SLASH_ITEMBROWSER2 = "/itembrowser"
end

function ItemBrowser_OnEvent(frame, event, arg1)
    if event == "ADDON_LOADED" and arg1 == "ItemBrowser" then
        ItemBrowserSaved = ItemBrowserSaved or {}

        RestorePosition(frame)
        Widget("Reset"):SetText(RESET or "Reset")
        _G["ItemBrowserFrameLevelMinLabel"]:SetText(RangeLabel("req"))
        _G["ItemBrowserFrameLevelMaxLabel"]:SetText("to")
        _G["ItemBrowserFrameIlvlMinLabel"]:SetText(RangeLabel("ilvl"))
        _G["ItemBrowserFrameIlvlMaxLabel"]:SetText("to")
        _G["ItemBrowserFrameUsableText"]:SetText(USABLE_ITEMS or "Usable Items")
        _G["ItemBrowserFrameTreeHeader"]:SetText("Categories")
        -- OptionsBoxTemplate draws its caption above its own top-left corner.
        _G["ItemBrowserFrameLevelsTitle"]:SetText("Levels")

        Widget("QuantityUp").step = 1
        Widget("QuantityDown").step = -1

        for _, name in ipairs({ "Quality", "Sort" }) do
            local dropdown = Widget(name)
            UIDropDownMenu_JustifyText(dropdown, "LEFT")
            UIDropDownMenu_SetWidth(dropdown, name == "Sort" and 130 or 108)
        end
        UIDropDownMenu_Initialize(Widget("Quality"), QualityDropDown_Initialize)
        UIDropDownMenu_Initialize(Widget("Sort"), SortDropDown_Initialize)

        BuildPresets(frame)
        ItemBrowserTree_Init()
        ApplyFilterWidgets()
        Widget("Quantity"):SetText(tostring(ItemBrowserSaved.quantity or 1))
        ItemBrowserLauncher_Init()
        ItemBrowser_OnSizeChanged(frame)

        if not D:IsLoaded() then
            DEFAULT_CHAT_FRAME:AddMessage("|cffff6060ItemBrowser|r: the generated item " ..
                "database is missing. Run client/addons/mod-item-browser/tools/regen.sh " ..
                "and reinstall the addon.")
        end
    elseif event == "PLAYER_TARGET_CHANGED" then
        UpdateGiveBar()
    end
end

function ItemBrowser_OnShow(frame)
    UpdateGiveBar()
    Feedback("")
    -- Always re-run on open. The Usable filter depends on the player's level and skills, so
    -- yesterday's result list is not necessarily today's.
    searchDirty = true
    sinceType = SEARCH_DELAY
    ItemBrowser_OnSizeChanged(frame)
end

function ItemBrowser_OnHide()
    ItemBrowserSaved.quantity = Quantity()
    pendingTooltip = nil
end

function ItemBrowser_OnUpdate(frame, elapsed)
    if scanning then
        if S:Step(SCAN_BUDGET) then
            ItemBrowser_FinishSearch()
        else
            ItemBrowser_UpdateStatus()
        end
    elseif searchDirty then
        sinceType = sinceType + elapsed
        if sinceType >= SEARCH_DELAY then
            StartSearch()
        end
    else
        -- Idle: get the lowercase name index built before the user's first keystroke needs
        -- it, a slice at a time. Once it is done this costs one comparison per frame.
        S:Prime(IDLE_BUDGET)
    end

    sincePrefetch = sincePrefetch + elapsed
    if sincePrefetch >= PREFETCH_INTERVAL then
        sincePrefetch = 0
        DrainPrefetch()
    end

    if pendingTooltip then
        if GetTime() > pendingTooltip.expires or not GameTooltip:IsOwned(pendingTooltip.row) then
            pendingTooltip = nil
        elseif RealTooltip(pendingTooltip.index, pendingTooltip.entry) then
            pendingTooltip = nil
        end
    end
end
