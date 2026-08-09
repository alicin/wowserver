--[[----------------------------------------------------------------------------------------
ItemBrowser -- behaviour.

Layout lives in UI.xml. This file is the wiring: the auction-house-style filter bar, the
budgeted search loop, the thirteen recycled result rows, tooltips, and the one button that
hands an item over.

THE TOOLTIP RULE, because it is the least obvious thing here.
=============================================================
A real item tooltip -- stats, sockets, set bonuses, flavour text, the red "Requires Level"
line in the right colour -- can only be drawn by the CLIENT, from item data the client holds.
An addon cannot fake it and should not try; the shipped database has the name, the icon and
six numbers, and that is all it will ever have.

On a 3.3.5a client that data arrives from the server on demand. Touching GetItemInfo() for an
item the client has never seen returns nil AND makes the client send CMSG_ITEM_QUERY_SINGLE;
the SMSG_ITEM_QUERY_SINGLE_RESPONSE lands a moment later and goes into itemcache.wdb, and from
then on the client can draw that item forever, across sessions. So there are three parts:

  1. PREFETCH. Every time the list is re-filled, the ids now on screen are queued. A few
     queries per PREFETCH_INTERVAL are issued from that queue -- rate limited, and each id
     asked at most once per session -- so an item you have merely scrolled past is usually
     already cached by the time you hover it.
  2. HOVER. GameTooltip:SetHyperlink(link) if GetItemInfo() has an answer: the genuine
     tooltip, identical to hovering the item in a bag, plus our own id/category footer.
  3. WAIT. Otherwise draw a summary from the shipped database, mark it with the client's own
     RETRIEVING_ITEM_INFO string, and keep polling GetItemInfo for TOOLTIP_WAIT seconds. The
     instant it resolves, the tooltip is replaced in place under the still-hovering cursor.

Polling is not laziness: 3.3.5 has no event for this. GET_ITEM_INFO_RECEIVED does not exist
until Mists, and there is no callback form of GetItemInfo. Polling one id per frame for six
seconds is the whole available API.

FAILURE MODE. If the server never answers -- the character is mid-loading-screen, the reply
was dropped, the item id is not in the server's item_template -- the summary is what you keep,
the poll gives up after TOOLTIP_WAIT, and moving the cursor away and back retries. The other
failure is worse because it is silent: itemcache.wdb is keyed by item id alone and is NOT
per-realm, so a client that has played on a server with a differently edited item 49623 will
answer instantly with that other server's data. Nothing an addon can detect. Deleting the
client's Cache/ directory is the fix.
------------------------------------------------------------------------------------------]]

local D = ItemBrowserData
local S = ItemBrowserSearch

local ROWS = 13              -- visible rows; must match the space UI.xml reserves
local ROW_HEIGHT = 30
local SEARCH_DELAY = 0.20    -- seconds of no typing before the search is started
local SCAN_BUDGET = 6000     -- rows of filtering per frame; ~2-3 ms, see Search.lua
local IDLE_BUDGET = 3000     -- rows of lowercase-index priming per idle frame
local TOOLTIP_WAIT = 6       -- seconds to keep waiting for the server's item data
local PREFETCH_INTERVAL = 0.2
local PREFETCH_PER_TICK = 4  -- => at most 20 item queries a second while scrolling
local MAX_QUANTITY = 1000

local rows = {}
local results, shown, matchedCount, cappedResults = {}, 0, 0, false
local searchNote = nil
local searchDirty = false
local sinceType = 0
local scanning = false
local updating = false       -- re-entrancy guard: FauxScrollFrame_Update can re-enter us
local settingFilters = false -- suppress OnTextChanged while filters are restored/reset
local selectedEntry = nil
local pendingTooltip = nil   -- { row, entry, expires }
local pendingGive = nil      -- captured before the confirmation popup, used after it

local prefetchQueue, prefetchSeen, sincePrefetch = {}, {}, 0

ItemBrowserSaved = ItemBrowserSaved or {}

-- item_template.InventoryType -> the FrameXML global that names the slot. Index 1 is HEAD;
-- InventoryType 0 means "not equippable" and has no label. Not generated because these are
-- FrameXML string names, not data: the client owns them and there is nothing to derive.
local INVTYPE_TOKEN = {
    "HEAD", "NECK", "SHOULDER", "BODY", "CHEST", "WAIST", "LEGS", "FEET", "WRIST", "HAND",
    "FINGER", "TRINKET", "WEAPON", "SHIELD", "RANGED", "CLOAK", "2HWEAPON", "BAG", "TABARD",
    "ROBE", "WEAPONMAINHAND", "WEAPONOFFHAND", "HOLDABLE", "AMMO", "THROWN", "RANGEDRIGHT",
    "QUIVER", "RELIC",
}

local ANY_CATEGORY = "All categories"
local ANY_SUBCATEGORY = "All subtypes"

-- Sentinel for the "no filter" entry in the two category dropdowns. It cannot be nil:
-- UIDropDownMenu_AddButton falls back to `button.value = info.text` when info.value is nil
-- (UIDropDownMenu.lua:336-342), so a nil value would come back to the click handler as the
-- string "All categories". -1 is not a class or subclass id and never will be.
local ANY = -1


-- =========================================================================================
-- small helpers
-- =========================================================================================

local function Widget(name)
    return _G["ItemBrowserFrame" .. name]
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

--- Contents of a numeric filter box as a number, or nil for "no bound".
local function BoxNumber(name)
    local box = Widget(name)
    local n = tonumber(box and box:GetText() or "")
    if not n then return nil end
    n = math.floor(n)
    if n < 0 then return nil end
    return n
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
    UpdateGiveBar()
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
        minQuality   = saved.minQuality or 0,
        minLevel     = BoxNumber("LevelMin"),
        maxLevel     = BoxNumber("LevelMax"),
        minItemLevel = BoxNumber("IlvlMin"),
        maxItemLevel = BoxNumber("IlvlMax"),
        usable       = Widget("Usable") and Widget("Usable"):GetChecked() and true or false,
    }
end

local function StartSearch()
    searchDirty = false
    local filter = CurrentFilter()
    -- Persist here rather than in OnHide: a client that is closed, or /reload-ed, with the
    -- window still open never fires OnHide, and losing the filters you just set to a crash is
    -- a small betrayal. The dropdowns already write straight to ItemBrowserSaved.
    local saved = ItemBrowserSaved
    saved.levelMin, saved.levelMax = filter.minLevel, filter.maxLevel
    saved.ilvlMin, saved.ilvlMax = filter.minItemLevel, filter.maxItemLevel
    saved.usable = filter.usable

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

function ItemBrowser_UpdateList()
    if updating then return end
    updating = true

    local scroll = Widget("ListScroll")
    FauxScrollFrame_Update(scroll, shown, ROWS, ROW_HEIGHT)
    -- FauxScrollFrame_GetOffset just returns frame.offset (UIPanelTemplates.lua:245-247),
    -- and nothing sets that field until the first OnVerticalScroll. The window can be
    -- filled before it has ever been scrolled, so the fallback is not paranoia.
    local offset = FauxScrollFrame_GetOffset(scroll) or 0

    for i = 1, ROWS do
        local row = rows[i]
        local index = (offset + i <= shown) and results[offset + i] or nil
        if index then
            local entry = D.entry[index]
            local _, _, class, subclass, _, itemLevel = D:Decode(index)
            local _, subLabel = D:CategoryLabel(class, subclass)
            row.index = index
            row.entry = entry
            local name = row:GetName()
            _G[name .. "Icon"]:SetTexture(D:IconPath(index))
            _G[name .. "Name"]:SetText((D:ColouredName(index)))
            _G[name .. "Category"]:SetText(subLabel or "")
            _G[name .. "Level"]:SetText(itemLevel > 0 and ("ilvl " .. itemLevel) or "")
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

function ItemBrowser_UpdateStatus()
    local status = Widget("Status")
    if not status then return end
    if scanning then
        status:SetText(string.format("|cffffd100Filtering %d%%...|r", S:Progress() * 100))
    elseif searchNote then
        status:SetText("|cffffd100" .. searchNote .. "|r")
    elseif matchedCount == 0 then
        status:SetText("|cffffd100Nothing matches these filters.|r")
    elseif cappedResults then
        status:SetText(string.format("%d matches, showing the best %d. Narrow it down.",
                                     matchedCount, shown))
    elseif matchedCount == D.rows then
        status:SetText(string.format("All %d items.", matchedCount))
    else
        status:SetText(string.format("%d of %d items.", matchedCount, D.rows))
    end
end

function ItemBrowser_FinishSearch()
    scanning = false
    results, shown, matchedCount, cappedResults, searchNote = S:Results()
    FauxScrollFrame_SetOffset(Widget("ListScroll"), 0)
    Widget("ListScrollScrollBar"):SetValue(0)
    ItemBrowser_UpdateList()
end

function ItemBrowser_SearchChanged(self)
    local hint = _G[self:GetName() .. "Hint"]
    if hint then
        if self:GetText() == "" then hint:Show() else hint:Hide() end
    end
    ItemBrowser_FilterChanged()
end

function ItemBrowser_ListOnLoad(self)
    -- No enableMouseWheel attribute exists in the 3.3.5 UI schema, so it is set here. The
    -- rows sit on top of this frame and do not take wheel events themselves, and an
    -- unhandled wheel walks up the parent chain, so one handler here covers the whole list.
    self:EnableMouseWheel(true)

    local scroll = _G[self:GetName() .. "Scroll"]
    FauxScrollFrame_SetOffset(scroll, 0)
    for i = 1, ROWS do
        local row = CreateFrame("Button", "ItemBrowserFrameRow" .. i, self,
                                "ItemBrowserRowTemplate")
        if i == 1 then
            row:SetPoint("TOPLEFT", scroll, "TOPLEFT", 0, 0)
        else
            row:SetPoint("TOPLEFT", rows[i - 1], "BOTTOMLEFT", 0, 0)
        end
        -- Rows and the scroll frame are siblings, so they default to the same frame level
        -- and the winner of a mouse hit is decided by creation order. Being explicit means
        -- the rows keep their clicks and tooltips no matter what order things load in.
        row:SetFrameLevel(scroll:GetFrameLevel() + 2)
        _G[row:GetName() .. "Selected"]:Hide()
        row:Hide()
        rows[i] = row
    end
end

function ItemBrowser_ListOnMouseWheel(self, delta)
    local scroll = _G[self:GetName() .. "Scroll"]
    local bar = _G[scroll:GetName() .. "ScrollBar"]
    local step = ROW_HEIGHT * 3
    bar:SetValue(bar:GetValue() - delta * step)
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
    local slot = INVTYPE_TOKEN[invType] and _G["INVTYPE_" .. INVTYPE_TOKEN[invType]]
    if slot then
        GameTooltip:AddDoubleLine("Slot", slot, 0.6, 0.6, 0.6, 0.9, 0.9, 0.9)
    end
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
    -- call is doing real work even on the branch where it returns nil.
    local _, link = GetItemInfo(entry)
    if not link then return false end
    GameTooltip:ClearLines()
    -- The genuine article: stats, sockets and their bonus, set membership and set bonuses,
    -- durability, flavour text, "Requires Level" in red when it is too high. None of that is
    -- in item_template in a form an addon could re-render, and all of it is in the client.
    GameTooltip:SetHyperlink(link)
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
-- the filter bar
-- =========================================================================================

local function SetDropDownText(widget, text)
    UIDropDownMenu_SetText(widget, text)
end

local function RefreshSubCategory()
    local dropdown = Widget("SubCategory")
    local cat = ItemBrowserSaved.class and D.category[ItemBrowserSaved.class]
    if not cat then
        ItemBrowserSaved.subclass = nil
        UIDropDownMenu_DisableDropDown(dropdown)
        SetDropDownText(dropdown, ANY_SUBCATEGORY)
        return
    end
    UIDropDownMenu_EnableDropDown(dropdown)
    local label = ANY_SUBCATEGORY
    if ItemBrowserSaved.subclass then
        for i = 1, #cat.sub do
            if cat.sub[i][1] == ItemBrowserSaved.subclass then label = cat.sub[i][3] end
        end
    end
    UIDropDownMenu_SetSelectedValue(dropdown, ItemBrowserSaved.subclass or ANY)
    SetDropDownText(dropdown, label)
end

local function CategorySelected(self)
    local class = (self.value ~= ANY) and self.value or nil
    ItemBrowserSaved.class = class
    ItemBrowserSaved.subclass = nil
    UIDropDownMenu_SetSelectedValue(Widget("Category"), self.value)
    SetDropDownText(Widget("Category"), class and D.category[class].name or ANY_CATEGORY)
    RefreshSubCategory()
    ItemBrowser_FilterChanged()
end

local function CategoryDropDown_Initialize()
    local current = ItemBrowserSaved.class
    local info = UIDropDownMenu_CreateInfo()
    info.text, info.value, info.func = ANY_CATEGORY, ANY, CategorySelected
    info.checked = (current == nil)
    UIDropDownMenu_AddButton(info)
    for i = 1, #D.categoryOrder do
        local cls = D.categoryOrder[i]
        local cat = D.category[cls]
        info = UIDropDownMenu_CreateInfo()
        -- The count is not decoration: "Permanent (1)" tells you not to bother, and it is
        -- the cheapest possible sanity check that the generated database is the one you
        -- think it is.
        info.text = string.format("%s  |cff808080(%d)|r", cat.name, cat.count)
        info.value = cls
        info.func = CategorySelected
        info.checked = (current == cls)
        UIDropDownMenu_AddButton(info)
    end
end

local function SubCategorySelected(self)
    ItemBrowserSaved.subclass = (self.value ~= ANY) and self.value or nil
    UIDropDownMenu_SetSelectedValue(Widget("SubCategory"), self.value)
    RefreshSubCategory()
    ItemBrowser_FilterChanged()
end

local function SubCategoryDropDown_Initialize()
    local cat = ItemBrowserSaved.class and D.category[ItemBrowserSaved.class]
    if not cat then return end
    local current = ItemBrowserSaved.subclass
    local info = UIDropDownMenu_CreateInfo()
    info.text, info.value, info.func = ANY_SUBCATEGORY, ANY, SubCategorySelected
    info.checked = (current == nil)
    UIDropDownMenu_AddButton(info)
    for i = 1, #cat.sub do
        local sub, count, label = cat.sub[i][1], cat.sub[i][2], cat.sub[i][3]
        info = UIDropDownMenu_CreateInfo()
        info.text = string.format("%s  |cff808080(%d)|r", label, count)
        info.value = sub
        info.func = SubCategorySelected
        info.checked = (current == sub)
        UIDropDownMenu_AddButton(info)
    end
end

local function QualityLabel(q)
    if not q or q == 0 then return "Any quality" end
    return D:ColouredQualityName(q) .. "|cffffffff+|r"
end

local function QualitySelected(self)
    ItemBrowserSaved.minQuality = self.value
    UIDropDownMenu_SetSelectedValue(Widget("Quality"), self.value)
    SetDropDownText(Widget("Quality"), QualityLabel(self.value))
    ItemBrowser_FilterChanged()
end

local function QualityDropDown_Initialize()
    local current = ItemBrowserSaved.minQuality or 0
    for q = 0, 7 do
        local info = UIDropDownMenu_CreateInfo()
        info.text = (q == 0) and "Any quality"
                    or (D:ColouredQualityName(q) .. " or better")
        info.value = q
        info.func = QualitySelected
        info.checked = (q == current)
        UIDropDownMenu_AddButton(info)
    end
end

--- Push the saved filter state into the widgets. Guarded, because setting an EditBox's text
--- fires OnTextChanged, which would otherwise queue a search per box on every login.
local function ApplyFilterWidgets()
    settingFilters = true
    local saved = ItemBrowserSaved
    Widget("LevelMin"):SetText(saved.levelMin and tostring(saved.levelMin) or "")
    Widget("LevelMax"):SetText(saved.levelMax and tostring(saved.levelMax) or "")
    Widget("IlvlMin"):SetText(saved.ilvlMin and tostring(saved.ilvlMin) or "")
    Widget("IlvlMax"):SetText(saved.ilvlMax and tostring(saved.ilvlMax) or "")
    Widget("Usable"):SetChecked(saved.usable and true or false)
    -- A saved class that no longer exists (the world DB changed under us) is dropped rather
    -- than left to index a nil category later.
    if saved.class and not D.category[saved.class] then
        saved.class, saved.subclass = nil, nil
    end
    UIDropDownMenu_SetSelectedValue(Widget("Category"), saved.class or ANY)
    SetDropDownText(Widget("Category"),
                    saved.class and D.category[saved.class].name or ANY_CATEGORY)
    RefreshSubCategory()
    UIDropDownMenu_SetSelectedValue(Widget("Quality"), saved.minQuality or 0)
    SetDropDownText(Widget("Quality"), QualityLabel(saved.minQuality))
    settingFilters = false
end

function ItemBrowser_ResetFilters()
    local saved = ItemBrowserSaved
    saved.class, saved.subclass, saved.minQuality = nil, nil, 0
    saved.levelMin, saved.levelMax, saved.ilvlMin, saved.ilvlMax = nil, nil, nil, nil
    saved.usable = false
    settingFilters = true
    Widget("Search"):SetText("")
    settingFilters = false
    ApplyFilterWidgets()
    _G["ItemBrowserFrameSearchHint"]:Show()
    searchDirty = true
    sinceType = SEARCH_DELAY
end


-- =========================================================================================
-- frame lifecycle
-- =========================================================================================

local function RestorePosition(frame)
    local pos = ItemBrowserSaved.position
    if not pos or not pos.point then return end
    frame:ClearAllPoints()
    frame:SetPoint(pos.point, UIParent, pos.relPoint or pos.point, pos.x or 0, pos.y or 0)
end

function ItemBrowser_StopMoving(frame)
    frame:StopMovingOrSizing()
    local point, _, relPoint, x, y = frame:GetPoint()
    -- Only the anchor is saved, never the frame object GetPoint hands back: that would keep
    -- a reference to UIParent alive in the SavedVariables file, which cannot be serialised.
    ItemBrowserSaved.position = { point = point, relPoint = relPoint, x = x, y = y }
end

function ItemBrowser_OnLoad(frame)
    frame:RegisterForDrag("LeftButton")
    frame:RegisterEvent("ADDON_LOADED")
    frame:RegisterEvent("PLAYER_TARGET_CHANGED")
    tinsert(UISpecialFrames, frame:GetName())      -- Escape closes it

    local function Say(text)
        DEFAULT_CHAT_FRAME:AddMessage("|cff40c0ffItemBrowser|r " .. text)
    end

    SlashCmdList["ITEMBROWSER"] = function(msg)
        msg = string.gsub(msg or "", "^%s*(.-)%s*$", "%1")

        if msg == "" then
            if frame:IsShown() then frame:Hide() else frame:Show() end
        elseif msg == "help" then
            Say("/ib              toggle the window")
            Say("/ib <text>       open and search for <text>")
            Say("/ib reset        clear every filter")
            Say("/ib status       database and transport information")
            Say("/ib chat|addon   force a command transport (see Transport.lua)")
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
        _G["ItemBrowserFrameLevelMinLabel"]:SetText(LEVEL_RANGE or "Level Range")
        _G["ItemBrowserFrameLevelMaxLabel"]:SetText("to")
        _G["ItemBrowserFrameIlvlMinLabel"]:SetText("Item level")
        _G["ItemBrowserFrameIlvlMaxLabel"]:SetText("to")
        _G["ItemBrowserFrameUsableText"]:SetText(USABLE_ITEMS or "Usable Items")

        for _, name in ipairs({ "Category", "SubCategory", "Quality" }) do
            local dropdown = Widget(name)
            UIDropDownMenu_JustifyText(dropdown, "LEFT")
            UIDropDownMenu_SetWidth(dropdown, name == "Quality" and 108 or 128)
        end
        UIDropDownMenu_Initialize(Widget("Category"), CategoryDropDown_Initialize)
        UIDropDownMenu_Initialize(Widget("SubCategory"), SubCategoryDropDown_Initialize)
        UIDropDownMenu_Initialize(Widget("Quality"), QualityDropDown_Initialize)

        ApplyFilterWidgets()
        Widget("Quantity"):SetText(tostring(ItemBrowserSaved.quantity or 1))

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
    Widget("Search"):SetFocus()
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
