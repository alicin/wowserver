--[[----------------------------------------------------------------------------------------
ItemBrowser -- data layer.

Holds the shipped item table and the accessors over it. Everything under Data/ is GENERATED
by tools/itemdb.py; this file is the hand-written half that the generated files plug into, so
it MUST load before Data\Data.xml (see ItemBrowser.toc).

Why the data is shipped at all: a 3.3.5a client only knows items that are in its local
itemcache.wdb, so GetItemInfo() returns nil for almost everything on a fresh install. An
addon that asks the client for 46,000 item names gets 46,000 nils. Names, qualities and
icons therefore come from the server's own item_template, baked into Lua at package time.

STORAGE SHAPE -- four parallel arrays, not 46,098 record tables:

    entry[i]   item id, STRICTLY ASCENDING (Find() binary-searches this)
    name[i]    display name, exactly the bytes item_template holds
    packed[i]  quality/invtype/class/subclass/reqlevel/itemlevel/restrict in one number
    iconid[i]  index into iconName[], which holds each distinct icon once

46k small tables would cost roughly 40 bytes of table header each before any content. Four
arrays cost eight bytes per slot. The parallel-array shape is the difference between an addon
that adds ~8 MB to the Lua heap and one that adds ~40 MB.

Data/Filters.lua adds the tables the filter bar needs that are not per row: category and
subcategory labels (read out of the client's own ItemClass.dbc / ItemSubClass.dbc, so they are
the same words the auction house uses), the inventory slots each subcategory actually contains
(the tree's third tier), the pooled class/race/skill restrictions the packed `restrict` field
indexes, and the weapon/armour proficiency map.
------------------------------------------------------------------------------------------]]

ItemBrowserData = {
    entry    = {},
    name     = {},
    packed   = {},
    iconid   = {},
    iconName = {},          -- replaced wholesale by Data/Icons.lua
    build    = nil,         -- set by Data/Meta.lua

    -- All set by Data/Filters.lua. Defaulted here so an install that copied the hand-written
    -- files but not the generated ones degrades to "no categories" instead of erroring on
    -- the first index of a nil table.
    category      = {},
    categoryOrder = {},
    slotToken     = {},
    limits        = { reqLevel = 80, itemLevel = 300 },
    restrict      = {},
    profSkill     = {},
    skillName     = {},
    classBit      = {},
    raceBit       = {},

    rows     = 0,
}

local D = ItemBrowserData
local floor = math.floor

-- Field widths, in the same order and with the same values as tools/itemdb.py FIELD_WIDTHS.
-- If you change one you MUST change the other; invariant #2 in the generator is what proves
-- they still agree.
local W_QUALITY, W_INVTYPE, W_CLASS, W_SUBCLASS, W_REQLEVEL, W_ITEMLVL
    = 16, 32, 32, 32, 128, 512

-- Precomputed divisors, so Decode() is six divisions and no repeated multiplication.
local DIV_INVTYPE  = W_QUALITY                                                    -- 16
local DIV_CLASS    = DIV_INVTYPE * W_INVTYPE                                      -- 512
local DIV_SUBCLASS = DIV_CLASS * W_CLASS                                          -- 16384
local DIV_REQLEVEL = DIV_SUBCLASS * W_SUBCLASS                                    -- 524288
local DIV_ITEMLVL  = DIV_REQLEVEL * W_REQLEVEL                                    -- 67108864
local DIV_RESTRICT = DIV_ITEMLVL * W_ITEMLVL                                      -- 34359738368

-- Search.lua's scan loop reads these instead of calling Decode(): a method call per row per
-- keystroke is the difference between a filter that costs 3 ms and one that costs 12.
D.DIV = {
    quality   = { 1,             W_QUALITY  },
    invtype   = { DIV_INVTYPE,   W_INVTYPE  },
    class     = { DIV_CLASS,     W_CLASS    },
    subclass  = { DIV_SUBCLASS,  W_SUBCLASS },
    reqlevel  = { DIV_REQLEVEL,  W_REQLEVEL },
    itemlevel = { DIV_ITEMLVL,   W_ITEMLVL  },
    restrict  = { DIV_RESTRICT,  0          },   -- top field, nothing above it to mask off
}

--- Append one generated shard. Called once per Data/Items_NN.lua, in load order.
-- Copies into the flat arrays rather than keeping the shards as separate blocks: one flat
-- array is what lets Find() binary-search and what lets the search loop be a plain numeric
-- for with no per-iteration bounds juggling. The copy is ~184k assignments in total, which
-- is a few milliseconds once, at load.
function ItemBrowserData:Chunk(entry, name, packed, iconid)
    local e, n, p, c = self.entry, self.name, self.packed, self.iconid
    local base = self.rows
    for i = 1, #entry do
        local j = base + i
        e[j] = entry[i]
        n[j] = name[i]
        p[j] = packed[i]
        c[j] = iconid[i]
    end
    self.rows = base + #entry
end

--- Unpack one row's small fields.
-- @return quality, invtype, class, subclass, reqlevel, itemlevel, restrict
-- Arithmetic, not bit.band: the record is 46 bits wide and WoW's LuaBitOp is 32-bit, so
-- bit.band would silently truncate the item level away. Doubles hold integers up to 2^53
-- exactly, and the widest value this encoding produces is about 7.0e13.
function ItemBrowserData:Decode(index)
    local m = self.packed[index]
    if not m then return 0, 0, 0, 0, 0, 0, 0 end
    return m % W_QUALITY,
           floor(m / DIV_INVTYPE) % W_INVTYPE,
           floor(m / DIV_CLASS) % W_CLASS,
           floor(m / DIV_SUBCLASS) % W_SUBCLASS,
           floor(m / DIV_REQLEVEL) % W_REQLEVEL,
           floor(m / DIV_ITEMLVL) % W_ITEMLVL,
           floor(m / DIV_RESTRICT)
end

--- The class/race/skill gate on a row, as Player::CanUseItem reads it.
-- @return allowableClass, allowableRace, requiredSkill, requiredSkillRank
-- Index 0 is not stored: 32,567 of the 46,098 rows have no restriction at all, and giving
-- them a pool slot would have meant 32k pointless numbers in the generated file.
function ItemBrowserData:Restriction(index)
    local slot = floor((self.packed[index] or 0) / DIV_RESTRICT)
    if slot == 0 then return -1, -1, 0, 0 end
    local r, base = self.restrict, (slot - 1) * 4
    return r[base + 1], r[base + 2], r[base + 3], r[base + 4]
end

--- Human labels for a row's category, e.g. "Armor", "Plate".
-- @return className, subClassName -- either may be nil if Data/Filters.lua is missing
function ItemBrowserData:CategoryLabel(class, subclass)
    local cat = self.category[class]
    if not cat then return nil, nil end
    for i = 1, #cat.sub do
        if cat.sub[i][1] == subclass then return cat.name, cat.sub[i][3] end
    end
    return cat.name, nil
end

--[[
Inventory slot labels.

The generated slotToken table maps item_template.InventoryType to the SUFFIX of a client
global -- 13 -> "WEAPON" -> INVTYPE_WEAPON -> "One-Hand". The words are therefore the
client's own, in the client's locale, and identical to what the character pane and the
auction house print; nothing in this addon spells a slot name.

InventoryType 0 means "not equippable" and deliberately has no entry: a Glyph has no slot,
and inventing a label for the absence of one would put a meaningless row in the tree.

Several tokens legitimately share a label (RANGED and RANGEDRIGHT are both "Ranged", CHEST
and ROBE are both "Chest", SHIELD and WEAPONOFFHAND are both "Off Hand"), which is why the
tree groups slots by this string and filters on the SET of ids behind it -- picking "Off
Hand" under Armor must not silently drop half the off-hand items.
]]
function ItemBrowserData:SlotLabel(invType)
    local token = self.slotToken[invType]
    if not token then return nil end
    -- The fallback is the token itself rather than nil: a client missing the global would
    -- otherwise produce an unclickable blank row in the tree.
    return _G["INVTYPE_" .. token] or token
end

--- Row index for an item id, or nil. Binary search; entry[] is ascending by construction.
function ItemBrowserData:Find(itemId)
    local e = self.entry
    local lo, hi = 1, self.rows
    while lo <= hi do
        local mid = floor((lo + hi) / 2)
        local v = e[mid]
        if v == itemId then
            return mid
        elseif v < itemId then
            lo = mid + 1
        else
            hi = mid - 1
        end
    end
    return nil
end

--- Full texture path for a row.
-- Passed through verbatim from ItemDisplayInfo.dbc. Three icon names in this client's data
-- legitimately end in a SPACE ("INV_Misc_Food_93_SkethylBerries "), and the .blp inside
-- locale-enUS.MPQ has the space in its filename too -- trimming here would break exactly
-- those icons. Five names in the whole table resolve to no file at all; the row template
-- keeps a question mark texture behind the icon so those draw as a question mark rather
-- than as a hole.
function ItemBrowserData:IconPath(index)
    local id = self.iconid[index]
    local name = id and self.iconName[id]
    if not name then return "Interface\\Icons\\INV_Misc_QuestionMark" end
    return "Interface\\Icons\\" .. name
end

--[[
Quality colours.

The default UI's ITEM_QUALITY_COLORS is built by UIParent.lua:96-103 with `for i = -1, 6`,
so on a 3.3.5a client there is NO entry for quality 7 -- and quality 7 is Heirloom, of which
this realm's item_template has plenty. Reading straight from that table would leave every
heirloom rendered in plain white with no hint that anything was missing.

So: take the client's colours where they exist (a browser row then matches a bag slot
exactly), and fall back to the published WotLK palette for anything the client's table does
not cover. Built once at load rather than per row.
]]
local QUALITY_HEX = {
    [0] = "|cff9d9d9d",   -- Poor
    [1] = "|cffffffff",   -- Common
    [2] = "|cff1eff00",   -- Uncommon
    [3] = "|cff0070dd",   -- Rare
    [4] = "|cffa335ee",   -- Epic
    [5] = "|cffff8000",   -- Legendary
    [6] = "|cffe6cc80",   -- Artifact
    [7] = "|cffe6cc80",   -- Heirloom
}
do
    local client = ITEM_QUALITY_COLORS
    if client then
        for q = 0, 7 do
            local c = client[q]
            if c and c.hex then QUALITY_HEX[q] = c.hex end
        end
    end
end

--- Colourised name for a row, e.g. "|cffa335eeShadowmourne|r".
-- @return coloured string, plain name, quality
function ItemBrowserData:ColouredName(index)
    local quality = self:Decode(index)
    local name = self.name[index] or ("item:" .. tostring(self.entry[index]))
    local hex = QUALITY_HEX[quality] or QUALITY_HEX[1]
    return hex .. name .. "|r", name, quality
end

function ItemBrowserData:QualityHex(quality)
    return QUALITY_HEX[quality] or QUALITY_HEX[1]
end

--[[
Quality names.

ITEM_QUALITY0_DESC .. ITEM_QUALITY7_DESC are real globals in this client
(FrameXML/GlobalStrings.lua lines 4490-4497), all eight of them -- unlike ITEM_QUALITY_COLORS,
which stops at 6. So the names are read from the client rather than typed here, which means
they are automatically whatever the client's locale calls them. The English fallback exists
only so a missing global cannot produce a blank dropdown entry.
]]
local QUALITY_FALLBACK = {
    [0] = "Poor", "Common", "Uncommon", "Rare", "Epic", "Legendary", "Artifact", "Heirloom",
}

function ItemBrowserData:QualityName(quality)
    return _G["ITEM_QUALITY" .. quality .. "_DESC"] or QUALITY_FALLBACK[quality]
           or tostring(quality)
end

--- "|cffa335eeEpic|r"
function ItemBrowserData:ColouredQualityName(quality)
    return self:QualityHex(quality) .. self:QualityName(quality) .. "|r"
end

--- Is the shipped database actually present and plausible?
-- The addon is useless without Data/, and Data/ is generated -- an install that copied the
-- hand-written files but not the generated ones is a real failure mode worth naming.
function ItemBrowserData:IsLoaded()
    return self.rows > 0 and #self.iconName > 0 and #self.categoryOrder > 0
end
