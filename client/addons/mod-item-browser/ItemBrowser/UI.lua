--[[----------------------------------------------------------------------------------------
ItemBrowser -- behaviour.

Layout lives in UI.xml. This file is the wiring: throttled search, the fourteen recycled
result rows, tooltips, and the one button that hands an item over.

THE TOOLTIP RULE, because it is the least obvious thing here.
A real item tooltip can only be drawn by the client, from item data the client has. On a
3.3.5a client that data arrives from the server on demand: touching GetItemInfo() for an
unknown id returns nil AND queues CMSG_ITEM_QUERY_SINGLE, and the answer lands a moment
later. So hovering a row does both halves:

    1. draw a tooltip immediately from the shipped database (name, quality, ilvl, required
       level, slot, class) so the row is never blank, and
    2. keep asking GetItemInfo for a few seconds; the moment the server's reply arrives,
       replace it with GameTooltip:SetHyperlink(realLink) -- the genuine article, with stats,
       flavour text, set bonuses, everything.

In practice the first hover of an item flickers from the summary to the real tooltip and
every hover after that is instant, because the client has cached it.
------------------------------------------------------------------------------------------]]

local D = ItemBrowserData
local ROWS = 14              -- visible rows; must match the space UI.xml reserves
local ROW_HEIGHT = 26
local SEARCH_DELAY = 0.20    -- seconds of no typing before the search runs
local TOOLTIP_WAIT = 6       -- seconds to keep waiting for the server's item data
local MAX_QUANTITY = 1000

local rows = {}
local results = {}
local matchedCount = 0
local searchMessage = nil
local searchDirty = false
local sinceType = 0
local updating = false       -- re-entrancy guard: FauxScrollFrame_Update can re-enter us
local selectedEntry = nil
local pendingTooltip = nil   -- { row, entry, expires }
local pendingGive = nil      -- captured before the confirmation popup, used after it

ItemBrowserSaved = ItemBrowserSaved or {}

-- item_template.class -> label. Not in any FrameXML global, and only ever shown in the
-- fallback tooltip, so a literal table is honest and cheaper than another generated file.
local ITEM_CLASS_NAMES = {
    [0] = "Consumable", "Container", "Weapon", "Gem", "Armor", "Reagent", "Projectile",
    "Trade Goods", "Generic", "Recipe", "Money", "Quiver", "Quest", "Key", "Permanent",
    "Miscellaneous", "Glyph",
}

-- item_template.InventoryType -> the FrameXML global that names the slot. Index 1 is HEAD;
-- InventoryType 0 means "not equippable" and has no label.
local INVTYPE_TOKEN = {
    "HEAD", "NECK", "SHOULDER", "BODY", "CHEST", "WAIST", "LEGS", "FEET", "WRIST", "HAND",
    "FINGER", "TRINKET", "WEAPON", "SHIELD", "RANGED", "CLOAK", "2HWEAPON", "BAG", "TABARD",
    "ROBE", "WEAPONMAINHAND", "WEAPONOFFHAND", "HOLDABLE", "AMMO", "THROWN", "RANGEDRIGHT",
    "QUIVER", "RELIC",
}

local QUALITY_NAMES = {
    [0] = "Poor", "Common", "Uncommon", "Rare", "Epic", "Legendary", "Artifact", "Heirloom",
}


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

--- Who gets the item, and is that a deliberate choice?
-- @return name, isSelf, warning
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

local function UpdateRecipient()
    local name, isSelf, warning = Recipient()
    local fs = Widget("Recipient")
    if not fs then return end
    if isSelf then
        local suffix = warning and ("|cffffd100 (" .. warning .. ")|r") or ""
        fs:SetText("Give to: |cffffffffyourself|r" .. suffix)
    else
        fs:SetText("Give to: |cff40ff40" .. name .. "|r")
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
-- results list
-- =========================================================================================

function ItemBrowser_UpdateList()
    if updating then return end
    updating = true

    local scroll = Widget("ListScroll")
    local total = #results
    FauxScrollFrame_Update(scroll, total, ROWS, ROW_HEIGHT)
    -- FauxScrollFrame_GetOffset just returns frame.offset (UIPanelTemplates.lua:245-247),
    -- and nothing sets that field until the first OnVerticalScroll. The window can be
    -- filled before it has ever been scrolled, so the fallback is not paranoia.
    local offset = FauxScrollFrame_GetOffset(scroll) or 0

    for i = 1, ROWS do
        local row = rows[i]
        local result = results[offset + i]
        if result then
            local index = result.index
            local entry = D.entry[index]
            local _, _, _, _, _, itemLevel = D:Decode(index)
            row.index = index
            row.entry = entry
            _G[row:GetName() .. "Icon"]:SetTexture(D:IconPath(index))
            _G[row:GetName() .. "Name"]:SetText((D:ColouredName(index)))
            _G[row:GetName() .. "Level"]:SetText(itemLevel > 0 and ("ilvl " .. itemLevel) or "")
            _G[row:GetName() .. "Id"]:SetText(tostring(entry))
            if selectedEntry == entry then
                _G[row:GetName() .. "Selected"]:Show()
            else
                _G[row:GetName() .. "Selected"]:Hide()
            end
            row:Show()
        else
            row.index = nil
            row.entry = nil
            row:Hide()
        end
    end

    local status = Widget("Status")
    if searchMessage then
        status:SetText("|cffffd100" .. searchMessage .. "|r")
    elseif total == 0 then
        status:SetText(string.format("%d items loaded. Type to search.", D.rows))
    elseif matchedCount > total then
        status:SetText(string.format("%d matches, showing the best %d.", matchedCount, total))
    else
        status:SetText(string.format("%d match%s.", total, total == 1 and "" or "es"))
    end

    updating = false
end

local function RunSearch()
    searchDirty = false
    local box = Widget("Search")
    local text = box and box:GetText() or ""
    local minQuality = ItemBrowserSaved.minQuality or 0
    results, matchedCount, searchMessage = ItemBrowserSearch:Run(text, minQuality)
    FauxScrollFrame_SetOffset(Widget("ListScroll"), 0)
    Widget("ListScrollScrollBar"):SetValue(0)
    ItemBrowser_UpdateList()
end

function ItemBrowser_SearchChanged(self)
    local hint = _G[self:GetName() .. "Hint"]
    if hint then
        if self:GetText() == "" then hint:Show() else hint:Hide() end
    end
    searchDirty = true
    sinceType = 0
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

local function FallbackTooltip(index, entry)
    local _, invType, class, subclass, reqLevel, itemLevel = D:Decode(index)
    local coloured, _, quality = D:ColouredName(index)

    GameTooltip:AddLine(coloured)
    if itemLevel > 0 then
        GameTooltip:AddLine(string.format(ITEM_LEVEL, itemLevel), 1, 1, 1)
    end
    if reqLevel > 0 then
        GameTooltip:AddLine(string.format(ITEM_MIN_LEVEL, reqLevel), 1, 1, 1)
    end

    local slot = INVTYPE_TOKEN[invType] and _G["INVTYPE_" .. INVTYPE_TOKEN[invType]]
    local kind = ITEM_CLASS_NAMES[class]
    if slot and kind then
        GameTooltip:AddDoubleLine(slot, kind, 1, 1, 1, 0.8, 0.8, 0.8)
    elseif slot then
        GameTooltip:AddLine(slot, 1, 1, 1)
    elseif kind then
        GameTooltip:AddLine(kind, 0.8, 0.8, 0.8)
    end

    GameTooltip:AddLine(" ")
    GameTooltip:AddDoubleLine("Item ID", tostring(entry), 0.6, 0.6, 0.6, 0.9, 0.9, 0.9)
    GameTooltip:AddDoubleLine("Quality", QUALITY_NAMES[quality] or tostring(quality),
                              0.6, 0.6, 0.6, 0.9, 0.9, 0.9)
    GameTooltip:AddLine("|cff808080Asking the server for the full tooltip...|r")
end

function ItemBrowser_RowEnter(row)
    local index = row.index
    if not index then return end
    local entry = row.entry

    GameTooltip:SetOwner(row, "ANCHOR_RIGHT")
    GameTooltip:ClearLines()

    -- Touching GetItemInfo is what makes the client ask the server for this item, so this
    -- call is doing real work even on the branch where it returns nil.
    local _, link = GetItemInfo(entry)
    if link then
        GameTooltip:SetHyperlink(link)
        pendingTooltip = nil
    else
        FallbackTooltip(index, entry)
        pendingTooltip = { row = row, entry = entry, expires = GetTime() + TOOLTIP_WAIT }
    end
    GameTooltip:Show()
end

function ItemBrowser_RowLeave()
    pendingTooltip = nil
    GameTooltip:Hide()
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
    ItemBrowser_UpdateList()
end

local function SelectedIndex()
    return selectedEntry and D:Find(selectedEntry) or nil
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
    local index = SelectedIndex()
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
-- quality filter
-- =========================================================================================

local function QualitySelected(self)
    ItemBrowserSaved.minQuality = self.value
    UIDropDownMenu_SetSelectedValue(Widget("Quality"), self.value)
    UIDropDownMenu_SetText(Widget("Quality"), self:GetText())
    RunSearch()
end

local function QualityDropDown_Initialize()
    local current = ItemBrowserSaved.minQuality or 0
    for q = 0, 7 do
        local info = UIDropDownMenu_CreateInfo()
        info.text = (q == 0) and "Any quality"
                    or (D:QualityHex(q) .. QUALITY_NAMES[q] .. "|r or better")
        info.value = q
        info.func = QualitySelected
        info.checked = (q == current)
        UIDropDownMenu_AddButton(info)
    end
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
            Say("/ib status       database and transport information")
            Say("/ib chat|addon   force a command transport (see Transport.lua)")
        elseif msg == "status" then
            local build = D.build
            Say("database: " .. (build and string.format(
                    "%d items, %d icons, %d shards, digest %s",
                    build.rows, build.icons, build.shards, build.digest)
                or "NOT LOADED, the generated Data/ files are missing"))
            Say("transport: " .. ItemBrowserTransport:Describe())
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
        local dropdown = Widget("Quality")
        UIDropDownMenu_Initialize(dropdown, QualityDropDown_Initialize)
        UIDropDownMenu_SetWidth(dropdown, 130)
        local q = ItemBrowserSaved.minQuality or 0
        UIDropDownMenu_SetSelectedValue(dropdown, q)
        UIDropDownMenu_SetText(dropdown, q == 0 and "Any quality"
                                         or (QUALITY_NAMES[q] .. " or better"))
        Widget("Quantity"):SetText(tostring(ItemBrowserSaved.quantity or 1))
        if not D:IsLoaded() then
            DEFAULT_CHAT_FRAME:AddMessage("|cffff6060ItemBrowser|r: the generated item " ..
                "database is missing. Run client/addons/mod-item-browser/tools/regen.sh " ..
                "and reinstall the addon.")
        end
    elseif event == "PLAYER_TARGET_CHANGED" then
        UpdateRecipient()
    end
end

function ItemBrowser_OnShow(frame)
    UpdateRecipient()
    Feedback("")
    ItemBrowser_UpdateList()
    Widget("Search"):SetFocus()
end

function ItemBrowser_OnHide()
    ItemBrowserSaved.quantity = Quantity()
    pendingTooltip = nil
end

function ItemBrowser_OnUpdate(frame, elapsed)
    if searchDirty then
        sinceType = sinceType + elapsed
        if sinceType >= SEARCH_DELAY then
            RunSearch()
        end
    end

    if pendingTooltip then
        if GetTime() > pendingTooltip.expires or not GameTooltip:IsOwned(pendingTooltip.row) then
            pendingTooltip = nil
        else
            local _, link = GetItemInfo(pendingTooltip.entry)
            if link then
                GameTooltip:SetHyperlink(link)
                GameTooltip:Show()
                pendingTooltip = nil
            end
        end
    end
end
