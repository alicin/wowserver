--[[----------------------------------------------------------------------------------------
ItemBrowser -- search.

Turns what the user typed into an ordered list of row indices. Kept out of the UI file
because the ranking rules are the part most likely to want tuning, and because a search that
takes 40 ms is a search that must never run on every keypress (see UI.lua's throttle).

RANKING. Substring matching alone puts "Bolt of Linen Cloth" above "Linen Cloth" for the
query "linen", which is the wrong answer every time. Matches are bucketed by how well they
match and only then sorted:

    tier 1  the id typed literally           "6948"        -> Hearthstone
    tier 2  the whole name                   "hearthstone" -> Hearthstone
    tier 3  the name starts with the query   "linen c"     -> Linen Cloth
    tier 4  a word in the name starts with it "cloth"      -> Linen Cloth, Wool Cloth
    tier 5  anywhere in the name             "inen"        -> Linen Cloth

Inside a tier: shorter name first (a shorter name containing the query is a closer match),
then ascending item id (stable, and roughly chronological by expansion).
------------------------------------------------------------------------------------------]]

ItemBrowserSearch = {}

local S = ItemBrowserSearch
local D = ItemBrowserData

local MAX_RESULTS = 400        -- most rows ever handed to the UI
local MAX_PER_TIER = 3000      -- collection cap per tier, bounds the sort
local MIN_QUERY = 2            -- below this every keystroke would match half the table

-- Lowercased names, built once on the first search.
-- Not shipped: it would double the addon's disk size for something string.lower reproduces
-- in about 30 ms. Not rebuilt per search either: that would be 46k string allocations on
-- every keystroke, which is what makes naive browsers stutter.
local lowerName = nil

local function BuildIndex()
    if lowerName then return end
    lowerName = {}
    local src, dst = D.name, lowerName
    for i = 1, D.rows do
        dst[i] = string.lower(src[i])
    end
end

--- True if `haystack` has a WORD starting with `needle` (both already lowercase).
-- Anchors on a space, so "cloth" hits "Linen Cloth" at tier 4 but "othe" does not.
local function WordPrefix(haystack, needle)
    if string.sub(haystack, 1, #needle) == needle then return true end
    return string.find(haystack, " " .. needle, 1, true) ~= nil
end

local function ByRank(a, b)
    if a.tier ~= b.tier then return a.tier < b.tier end
    if a.len ~= b.len then return a.len < b.len end
    return a.entry < b.entry
end

--- Run a search.
-- @param text        raw contents of the search box
-- @param minQuality  0..7, rows below this quality are dropped (0 keeps everything)
-- @return results    array of { index = rowIndex } ordered best first, at most MAX_RESULTS
-- @return matched    how many rows matched in total, before the display cap
-- @return message    nil, or a string explaining why `results` is empty
function ItemBrowserSearch:Run(text, minQuality)
    if not D:IsLoaded() then
        return {}, 0, "Item database not loaded -- run tools/regen.sh and reinstall the addon."
    end

    local query = string.lower(string.gsub(text or "", "^%s*(.-)%s*$", "%1"))
    local asId = tonumber(query)
    if query == "" then
        return {}, 0, nil
    end
    if #query < MIN_QUERY and not asId then
        return {}, 0, "Type at least " .. MIN_QUERY .. " characters."
    end

    BuildIndex()
    minQuality = minQuality or 0

    local buckets = { {}, {}, {}, {}, {} }
    local counts = { 0, 0, 0, 0, 0 }
    local matched = 0

    -- Tier 1: the literal id. One binary search, so an exact id always wins even when the
    -- same digits appear inside 300 item names.
    if asId then
        local index = D:Find(asId)
        if index and select(1, D:Decode(index)) >= minQuality then
            matched = matched + 1
            counts[1] = 1
            buckets[1][1] = { index = index, tier = 1, len = 0, entry = asId }
        end
    end

    local names, entries = lowerName, D.entry
    for i = 1, D.rows do
        local name = names[i]
        local at = string.find(name, query, 1, true)
        if at then
            local tier
            if name == query then
                tier = 2
            elseif at == 1 then
                tier = 3
            elseif WordPrefix(name, query) then
                tier = 4
            else
                tier = 5
            end
            -- Quality is only decoded for rows that already matched by name, which is why
            -- the filter is free: the scan above touches one array.
            if minQuality == 0 or select(1, D:Decode(i)) >= minQuality then
                matched = matched + 1
                local n = counts[tier]
                if n < MAX_PER_TIER then
                    n = n + 1
                    counts[tier] = n
                    buckets[tier][n] = { index = i, tier = tier, len = #name, entry = entries[i] }
                end
            end
        end
    end

    -- Sort tier by tier and stop as soon as the display cap is full: for the common case
    -- (a good tier-2/3 match) the huge tier-5 bucket is never sorted at all.
    local results = {}
    for tier = 1, 5 do
        local bucket = buckets[tier]
        if #bucket > 0 then
            table.sort(bucket, ByRank)
            for i = 1, #bucket do
                if #results >= MAX_RESULTS then break end
                results[#results + 1] = bucket[i]
            end
        end
        if #results >= MAX_RESULTS then break end
    end

    local message = nil
    if matched == 0 then
        message = "No item matches \"" .. text .. "\"."
    end
    return results, matched, message
end

function ItemBrowserSearch:MaxResults()
    return MAX_RESULTS
end
