--[[----------------------------------------------------------------------------------------
ItemBrowser -- the category tree.

The zero-typing half of the filter bar: three tiers, click your way down them.

    Weapon                      item_template.class
      Bows                      item_template.subclass
        Ranged                  item_template.InventoryType, grouped by the slot's name

WHY IT LOOKS EXACTLY LIKE THE AUCTION HOUSE'S
---------------------------------------------
Because it is the same widget doing the same job, and a GM who has used the AH already knows
how this works. The stock browse pane keeps a flat list of the currently VISIBLE filter rows
and re-fills a fixed pool of buttons from a scroll offset -- Blizzard_AuctionUI.lua's
OPEN_FILTER_LIST / AuctionFrameFilters_UpdateClasses -- and clicking a class expands it,
clicking it again collapses it. This file is that, over the local database, and the buttons
inherit the AH's own textures (see ItemBrowserTreeNodeTemplate in UI.xml).

WHERE THE TAXONOMY COMES FROM, AND WHY NONE OF IT IS TYPED HERE
---------------------------------------------------------------
All of it is generated into Data/Filters.lua by tools/itemdb.py:

  * class and subclass LABELS come from the client's own ItemClass.dbc and ItemSubClass.dbc,
    which is where the auction house gets the words in its dropdowns. The verbose column
    wins, which is why this tree says "One-Handed Axes" and "Two-Handed Axes" rather than
    "Axe" twice.
  * which subclasses EXIST under a class, and which slots exist under a subclass, are counted
    off the live item_template. No branch can be opened onto an empty list, and "Bows" offers
    Ranged and nothing else because that is what the 308 bows in the table actually are.
  * slot labels are the client's INVTYPE_* globals, looked up at draw time, so they are in
    the player's locale and identical to the words on the character pane.

SLOTS ARE GROUPED BY LABEL, AND FILTER AS A SET
-----------------------------------------------
Several inventory types share a name: INVTYPE_CHEST and INVTYPE_ROBE are both "Chest",
INVTYPE_SHIELD and INVTYPE_WEAPONOFFHAND are both "Off Hand", INVTYPE_RANGED and
INVTYPE_RANGEDRIGHT are both "Ranged". Listing them separately would put two identical rows
in the tree and make picking one silently hide half the matching items, so identical labels
collapse into a single row whose filter is the SET of ids behind it.
------------------------------------------------------------------------------------------]]

local D = ItemBrowserData

local NODE_HEIGHT = 20       -- must match the OnVerticalScroll step in UI.xml
local MIN_NODES = 4
local MAX_NODES = 60

local buttons = {}
local visibleNodes = 0
local nodes = {}
local selectedSlots = nil    -- the set the current slot row filters on, or nil

local ALL_ITEMS = "All items"


-- =========================================================================================
-- the visible node list
-- =========================================================================================

--- The slot rows under one subcategory: the generated (InventoryType, count) pairs, grouped
--- by the label the client gives each type, in ascending slot order.
-- @return array of { label, count, slots = { [invType] = true } }
local function SlotGroups(subEntry)
    local pairsList = subEntry[4]
    if not pairsList then return {} end
    local groups, byLabel = {}, {}
    for i = 1, #pairsList - 1, 2 do
        local invType, count = pairsList[i], pairsList[i + 1]
        -- InventoryType 0 is "not equippable" and has no slot name. Those items stay
        -- reachable through the subcategory row above; inventing a row for them would put
        -- a nameless entry in the tree.
        if invType ~= 0 then
            local label = D:SlotLabel(invType)
            if label then
                local group = byLabel[label]
                if not group then
                    group = { label = label, count = 0, slots = {} }
                    byLabel[label] = group
                    groups[#groups + 1] = group
                end
                group.count = group.count + count
                group.slots[invType] = true
            end
        end
    end
    return groups
end

--- Rebuild the flat list of rows that are currently visible, and work out which slot set the
--- selection implies. Cheap: at most every class, plus one class's subclasses, plus one
--- subclass's slots -- about 40 rows, not 46,098.
local function BuildNodes()
    local saved = ItemBrowserSaved
    nodes = {}
    selectedSlots = nil

    nodes[1] = {
        level = 0, label = ALL_ITEMS, count = D.rows, all = true,
        selected = (saved.class == nil),
    }

    for i = 1, #D.categoryOrder do
        local cls = D.categoryOrder[i]
        local cat = D.category[cls]
        nodes[#nodes + 1] = {
            level = 0, label = cat.name, count = cat.count, class = cls,
            selected = (saved.class == cls and saved.subclass == nil),
            expanded = (saved.class == cls),
        }
        if saved.class == cls then
            for s = 1, #cat.sub do
                local subEntry = cat.sub[s]
                local sub = subEntry[1]
                nodes[#nodes + 1] = {
                    level = 1, label = subEntry[3], count = subEntry[2],
                    class = cls, subclass = sub,
                    selected = (saved.subclass == sub and saved.slotKey == nil),
                    expanded = (saved.subclass == sub),
                }
                if saved.subclass == sub then
                    local groups = SlotGroups(subEntry)
                    for g = 1, #groups do
                        local group = groups[g]
                        local chosen = (saved.slotKey == group.label)
                        nodes[#nodes + 1] = {
                            level = 2, label = group.label, count = group.count,
                            class = cls, subclass = sub, slotKey = group.label,
                            slots = group.slots, selected = chosen,
                            last = (g == #groups),
                        }
                        if chosen then selectedSlots = group.slots end
                    end
                    -- A slot that was chosen and then vanished (the database changed under a
                    -- saved variable) must not keep filtering invisibly.
                    if saved.slotKey and not selectedSlots then saved.slotKey = nil end
                end
            end
        end
    end
end

--- The slot set the tree is currently filtering on, or nil. Read by UI.lua's CurrentFilter.
function ItemBrowserTree_SelectedSlots()
    return selectedSlots
end


-- =========================================================================================
-- drawing
-- =========================================================================================

local function EnsureButtons(count)
    if count > MAX_NODES then count = MAX_NODES end
    if count < MIN_NODES then count = MIN_NODES end
    local tree = _G["ItemBrowserFrameTree"]
    local scroll = _G["ItemBrowserFrameTreeScroll"]
    for i = #buttons + 1, count do
        local button = CreateFrame("Button", "ItemBrowserFrameTreeNode" .. i, tree,
                                   "ItemBrowserTreeNodeTemplate")
        button:SetHeight(NODE_HEIGHT)
        if i == 1 then
            button:SetPoint("TOPLEFT", scroll, "TOPLEFT", 0, 0)
            button:SetPoint("TOPRIGHT", scroll, "TOPRIGHT", 0, 0)
        else
            button:SetPoint("TOPLEFT", buttons[i - 1], "BOTTOMLEFT", 0, 0)
            button:SetPoint("TOPRIGHT", buttons[i - 1], "BOTTOMRIGHT", 0, 0)
        end
        button:SetFrameLevel(scroll:GetFrameLevel() + 2)
        button:Hide()
        buttons[i] = button
    end
    visibleNodes = count
end

--- One row, dressed the way the auction house dresses its own three tiers
--- (FilterButton_SetType in Blizzard_AuctionUI.lua): the class tier keeps the full filter
--- background, the subclass tier fades it, and the slot tier drops it entirely and draws the
--- little elbow instead.
local function DrawNode(button, node)
    local name = button:GetName()
    local text = _G[name .. "NormalText"]
    local normal = _G[name .. "NormalTexture"]
    local lines = _G[name .. "Lines"]

    local count = node.count and ("  |cff808080" .. node.count .. "|r") or ""
    if node.level == 0 then
        button:SetText(node.label .. count)
        text:SetPoint("LEFT", button, "LEFT", 6, 0)
        normal:SetAlpha(1.0)
        lines:Hide()
    elseif node.level == 1 then
        button:SetText("|cffffffff" .. node.label .. "|r" .. count)
        text:SetPoint("LEFT", button, "LEFT", 14, 0)
        normal:SetAlpha(0.4)
        lines:Hide()
    else
        button:SetText("|cffffffff" .. node.label .. "|r" .. count)
        text:SetPoint("LEFT", button, "LEFT", 24, 0)
        normal:SetAlpha(0.0)
        if node.last then
            lines:SetTexCoord(0.4375, 0.875, 0, 0.625)
        else
            lines:SetTexCoord(0, 0.4375, 0, 0.625)
        end
        lines:Show()
    end

    if node.selected then button:LockHighlight() else button:UnlockHighlight() end
    button.node = node
    button:Show()
end

function ItemBrowserTree_Update()
    local scroll = _G["ItemBrowserFrameTreeScroll"]
    if not scroll then return end
    FauxScrollFrame_Update(scroll, #nodes, visibleNodes, NODE_HEIGHT)
    local offset = FauxScrollFrame_GetOffset(scroll) or 0
    for i = 1, #buttons do
        local node = (i <= visibleNodes) and nodes[offset + i] or nil
        if node then
            DrawNode(buttons[i], node)
        else
            buttons[i].node = nil
            buttons[i]:Hide()
        end
    end
end

--- Rebuild the model and redraw. Everything that changes the selection ends here.
function ItemBrowserTree_Refresh()
    BuildNodes()
    ItemBrowserTree_Update()
end

function ItemBrowserTree_Resized()
    local scroll = _G["ItemBrowserFrameTreeScroll"]
    if not scroll then return end
    local fit = math.floor((scroll:GetHeight() or 0) / NODE_HEIGHT)
    if fit ~= visibleNodes then
        EnsureButtons(fit)
        ItemBrowserTree_Update()
    end
end

function ItemBrowserTree_OnLoad(self)
    self:EnableMouseWheel(true)
    FauxScrollFrame_SetOffset(_G[self:GetName() .. "Scroll"], 0)
    EnsureButtons(MIN_NODES)
end

function ItemBrowserTree_OnMouseWheel(self, delta)
    local scroll = _G[self:GetName() .. "Scroll"]
    local bar = _G[scroll:GetName() .. "ScrollBar"]
    bar:SetValue(bar:GetValue() - delta * NODE_HEIGHT * 3)
end

function ItemBrowserTree_Init()
    BuildNodes()
    ItemBrowserTree_Update()
end

--- Used by Reset: nothing selected, nothing expanded.
function ItemBrowserTree_Collapse()
    ItemBrowserSaved.class, ItemBrowserSaved.subclass, ItemBrowserSaved.slotKey = nil, nil, nil
    ItemBrowserTree_Refresh()
end


-- =========================================================================================
-- clicking
-- =========================================================================================

--- Clicking a row selects it AND opens it; clicking the row that is already selected closes
--- it and hands the filter back to its parent. That is the auction house's behaviour
--- (AuctionFrameFilter_OnClick) and it means the tree needs no separate expand arrows.
function ItemBrowserTree_NodeClick(self)
    local node = self.node
    if not node then return end
    local saved = ItemBrowserSaved

    if node.all then
        saved.class, saved.subclass, saved.slotKey = nil, nil, nil
    elseif node.level == 0 then
        if saved.class == node.class then
            saved.class, saved.subclass, saved.slotKey = nil, nil, nil
        else
            saved.class, saved.subclass, saved.slotKey = node.class, nil, nil
        end
    elseif node.level == 1 then
        if saved.subclass == node.subclass then
            saved.subclass, saved.slotKey = nil, nil
        else
            saved.subclass, saved.slotKey = node.subclass, nil
        end
    else
        if saved.slotKey == node.slotKey then
            saved.slotKey = nil
        else
            saved.slotKey = node.slotKey
        end
    end

    ItemBrowserTree_Refresh()
    ItemBrowser_FilterChangedNow()
end

function ItemBrowserTree_NodeEnter(self)
    local node = self.node
    if not node then return end
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:ClearLines()
    GameTooltip:AddLine(node.label)
    if node.count then
        GameTooltip:AddLine(node.count .. " items in the database", 1, 1, 1)
    end
    if node.all then
        GameTooltip:AddLine("Clears the category filter.", 0.7, 0.7, 0.7, true)
    elseif node.selected then
        GameTooltip:AddLine("Click again to go back up a level.", 0.7, 0.7, 0.7, true)
    elseif node.level == 0 then
        GameTooltip:AddLine("Click to filter by this category and see its subcategories.",
                            0.7, 0.7, 0.7, true)
    elseif node.level == 1 then
        GameTooltip:AddLine("Click to filter by this subcategory and see its equipment slots.",
                            0.7, 0.7, 0.7, true)
    else
        GameTooltip:AddLine("Click to filter by this equipment slot.", 0.7, 0.7, 0.7, true)
    end
    GameTooltip:Show()
end
