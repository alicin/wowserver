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
    packed[i]  quality/invtype/class/subclass/reqlevel/itemlevel in one number
    iconid[i]  index into iconName[], which holds each distinct icon once

46k small tables would cost roughly 40 bytes of table header each before any content. Four
arrays cost eight bytes per slot. The parallel-array shape is the difference between an addon
that adds ~8 MB to the Lua heap and one that adds ~40 MB.
------------------------------------------------------------------------------------------]]

ItemBrowserData = {
    entry    = {},
    name     = {},
    packed   = {},
    iconid   = {},
    iconName = {},          -- replaced wholesale by Data/Icons.lua
    build    = nil,         -- set by Data/Meta.lua
    rows     = 0,
}

local D = ItemBrowserData
local floor = math.floor

-- Field widths, in the same order and with the same values as tools/itemdb.py FIELD_WIDTHS.
-- If you change one you MUST change the other; invariant #2 in the generator is what proves
-- they still agree.
local W_QUALITY, W_INVTYPE, W_CLASS, W_SUBCLASS, W_REQLEVEL = 16, 32, 32, 32, 128

-- Precomputed divisors, so Decode() is five divisions and no repeated multiplication.
local DIV_INVTYPE  = W_QUALITY                                                    -- 16
local DIV_CLASS    = DIV_INVTYPE * W_INVTYPE                                      -- 512
local DIV_SUBCLASS = DIV_CLASS * W_CLASS                                          -- 16384
local DIV_REQLEVEL = DIV_SUBCLASS * W_SUBCLASS                                    -- 524288
local DIV_ITEMLVL  = DIV_REQLEVEL * W_REQLEVEL                                    -- 67108864

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
-- @return quality, invtype, class, subclass, reqlevel, itemlevel
-- Arithmetic, not bit.band: the record is 35 bits wide and WoW's LuaBitOp is 32-bit, so
-- bit.band would silently truncate the item level away. Doubles hold integers up to 2^53
-- exactly, and the widest value this encoding produces is about 3.4e10.
function ItemBrowserData:Decode(index)
    local m = self.packed[index]
    if not m then return 0, 0, 0, 0, 0, 0 end
    return m % W_QUALITY,
           floor(m / DIV_INVTYPE) % W_INVTYPE,
           floor(m / DIV_CLASS) % W_CLASS,
           floor(m / DIV_SUBCLASS) % W_SUBCLASS,
           floor(m / DIV_REQLEVEL) % W_REQLEVEL,
           floor(m / DIV_ITEMLVL)
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

--- Is the shipped database actually present and plausible?
-- The addon is useless without Data/, and Data/ is generated -- an install that copied the
-- hand-written files but not the generated ones is a real failure mode worth naming.
function ItemBrowserData:IsLoaded()
    return self.rows > 0 and #self.iconName > 0
end
