--[[----------------------------------------------------------------------------------------
ItemBrowser -- ways in.

Three of them, because a window nobody can find is a window nobody uses:

  * the MINIMAP BUTTON, which is the obvious one. Left-click opens and closes the browser;
    drag it anywhere around the minimap and the angle is remembered.
  * a KEYBIND, under Key Bindings -> Item Browser. Bindings.xml is picked up automatically
    by the client from the addon folder -- it is never listed in the .toc -- and the two
    BINDING_* globals that give it a readable name are set in UI.lua's OnLoad.
  * /ib, which was always there.

WHY THE BUTTON IS HAND-ROLLED. LibDBIcon is the usual way, and this pack ships no Ace
libraries; a minimap button is thirty lines of trigonometry and copying the stock border
texture, which is cheaper than a library dependency for every addon in the pack to disagree
about the version of.

THE POSITION MATHS. The button is parented to Minimap and placed on a circle around its
centre, so it follows the minimap wherever another addon has moved it. While dragging, the
cursor position from GetCursorPosition() is in SCREEN pixels and the frame coordinates are in
the minimap's own scale, hence the division by GetEffectiveScale() before the angle is taken.
Getting that wrong is the classic minimap-button bug where the icon lags the cursor by a
factor of the UI scale.
------------------------------------------------------------------------------------------]]

local RADIUS = 80            -- distance from the minimap's centre, in minimap-scale pixels
local DEFAULT_ANGLE = 198    -- degrees; lower-left, where the fewest addons squat

local button = nil


local function Position()
    if not button then return end
    local angle = math.rad(ItemBrowserSaved.minimapAngle or DEFAULT_ANGLE)
    button:SetPoint("CENTER", Minimap, "CENTER",
                    RADIUS * math.cos(angle), RADIUS * math.sin(angle))
end

local function OnUpdate(self)
    if not self.dragging then return end
    local scale = Minimap:GetEffectiveScale()
    local cx, cy = GetCursorPosition()
    local mx, my = Minimap:GetCenter()
    if not mx or not cx or scale == 0 then return end
    cx, cy = cx / scale, cy / scale
    ItemBrowserSaved.minimapAngle = math.deg(math.atan2(cy - my, cx - mx))
    self:ClearAllPoints()
    Position()
end

local function OnEnter(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:ClearLines()
    GameTooltip:AddLine("Item Browser")
    GameTooltip:AddLine("Left-click to open or close it.", 1, 1, 1)
    GameTooltip:AddLine("Drag to move this button around the minimap.", 0.7, 0.7, 0.7)
    GameTooltip:AddLine("/ib, or bind a key under Key Bindings -> Item Browser.",
                        0.7, 0.7, 0.7)
    GameTooltip:Show()
end

--- Build the button. Called once, from ADDON_LOADED, because it reads SavedVariables.
function ItemBrowserLauncher_Init()
    if button then
        Position()
        return button
    end
    if not Minimap then return nil end          -- no minimap: nothing to hang it on

    button = CreateFrame("Button", "ItemBrowserMinimapButton", Minimap)
    button:SetWidth(31)
    button:SetHeight(31)
    button:SetFrameStrata("MEDIUM")
    button:SetFrameLevel(Minimap:GetFrameLevel() + 8)

    local icon = button:CreateTexture(nil, "BACKGROUND")
    icon:SetTexture("Interface\\Icons\\INV_Misc_Spyglass_02")
    icon:SetWidth(20)
    icon:SetHeight(20)
    icon:SetPoint("TOPLEFT", button, "TOPLEFT", 7, -5)
    -- Crops the dark frame baked into every Interface\Icons\ .blp, the same trim the result
    -- rows and every action button use.
    icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)

    -- The stock ring. Drawn in OVERLAY so it sits on top of the icon's square corners, which
    -- is what makes a minimap button look round.
    local border = button:CreateTexture(nil, "OVERLAY")
    border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
    border:SetWidth(53)
    border:SetHeight(53)
    border:SetPoint("TOPLEFT", button, "TOPLEFT", 0, 0)

    button:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")

    button:RegisterForDrag("LeftButton")
    button:SetScript("OnDragStart", function(self)
        self.dragging = true
        self:SetScript("OnUpdate", OnUpdate)
    end)
    button:SetScript("OnDragStop", function(self)
        self.dragging = nil
        self:SetScript("OnUpdate", nil)
    end)
    button:SetScript("OnClick", function() ItemBrowser_Toggle() end)
    button:SetScript("OnEnter", OnEnter)
    button:SetScript("OnLeave", function() GameTooltip:Hide() end)

    Position()
    if ItemBrowserSaved.minimapHide then button:Hide() else button:Show() end
    return button
end

--- /ib minimap. @return true if the button is now visible.
function ItemBrowserLauncher_Toggle()
    if not button then return false end
    if ItemBrowserSaved.minimapHide then
        ItemBrowserSaved.minimapHide = nil
        button:Show()
        return true
    end
    ItemBrowserSaved.minimapHide = true
    button:Hide()
    return false
end
