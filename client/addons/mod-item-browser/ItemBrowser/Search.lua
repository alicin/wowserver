--[[----------------------------------------------------------------------------------------
ItemBrowser -- filtering and search.

Turns the filter bar's state into an ordered list of row indices. Kept out of the UI file
because the ranking rules are the part most likely to want tuning, and because scanning 46,098
rows is the one thing in this addon that can visibly cost the client a frame.

THE FILTER SET is the stock 3.3.5 auction house's, over the local database:

    category / subcategory   item_template class + subclass, labelled from the client's own
                             ItemClass.dbc / ItemSubClass.dbc (see Data/Filters.lua)
    slot                     InventoryType, as a SET: the tree groups slots by the label the
                             client gives them, and "Off Hand" is two ids (INVTYPE_SHIELD and
                             INVTYPE_WEAPONOFFHAND), "Chest" is two more (CHEST and ROBE)
    quality                  minimum, the way the AH's dropdown works
    required level           min .. max, the AH's "Level Range" boxes
    item level               min .. max, which the AH does not have and a GM wants
    usable                   AuctionHouseUsablePlayerInfo::PlayerCanUseItem, evaluated here
    name                     substring, ranked

HOW IT STAYS RESPONSIVE
-----------------------
Three separate things, because there are three separate costs.

1. THE SCAN IS CHUNKED. A search is a job, not a call: Begin() sets it up and Step(budget)
   advances it by at most `budget` rows, so the UI can spend ~3 ms per frame on it and never
   more. A full unfiltered pass over 46,098 rows is roughly 6,000 rows per frame for eight
   frames -- an eighth of a second to settle, with the client still drawing at full rate. The
   alternative, one 25 ms blocking pass on every keystroke, is exactly the stutter that makes
   browsers feel broken.

2. NOTHING IS DECODED THAT DOES NOT HAVE TO BE. The scan reads the packed number directly with
   two arithmetic ops per field instead of calling Data:Decode(), and tests the fields in
   cheapest-and-most-selective-first order: category (2 ops) before quality (1) before the
   level ranges (4) before the restriction lookup before string.find. Anything a row fails on
   early costs nothing further.

3. THE SORT IS ONLY PAID WHEN IT BUYS SOMETHING. With no name typed the results come out in
   ascending item id -- which is the order the arrays are already in -- so there is no sort at
   all, and the result list can hold every row that matched. With a name typed the matches are
   ranked, and ranking is capped at MAX_RANKED; the sort key is packed into a single number so
   table.sort runs on its default numeric comparator (C) rather than on a Lua function.

WORST CASE, after all of that: no name, no filters, everything matches -> a 46,098-element
array of integers, plus one sort over it if the order is anything but the default. That is
fine to hold and fine to page, because the window instantiates only as many row widgets as
fit on screen (about two dozen) and re-fills them from an offset; the size of the result list
never changes how much drawing happens.

RANKING. Substring matching alone puts "Bolt of Linen Cloth" above "Linen Cloth" for the
query "linen", which is the wrong answer every time. Matches are bucketed by how well they
match and only then sorted:

    tier 1  the id typed literally            "6948"       -> Hearthstone
    tier 2  the whole name                    "hearthstone"-> Hearthstone
    tier 3  the name starts with the query    "linen b"    -> Linen Bag
    tier 4  a word in the name starts with it "cloth"      -> Linen Cloth, Wool Cloth
    tier 5  anywhere in the name              "inen"       -> Linen Cloth

Inside a tier: shorter name first (a shorter name containing the query is a closer match),
then ascending item id (stable, and roughly chronological by expansion). So "linen" gives
Linen Bag, Linen Belt, Linen Boots, ... and puts "Bolt of Linen Cloth" below all of them --
which is the whole point -- but it does NOT promote Linen Cloth over Linen Cloak, because by
this rule nothing distinguishes them.

SORTING, and why every order is a NUMBER
----------------------------------------
"Best match" is the ranking above. The other orders -- item level, required level, quality,
name, item id, each way up -- are one table.sort over the matched rows, and every one of them
sorts a single packed number so table.sort uses its built-in C comparator:

    key = value * KEY_ROW + rowIndex          ascending
    key = (limit - value) * KEY_ROW + rowIndex descending

The row index rides in the low bits, so ties break by ascending item id and the order is
stable without a comparator function. A Lua comparator over 46,098 rows is ~715,000 calls
back into the interpreter; the packed key turns that into a C-level number compare, and it is
the difference between a sort you notice and one you do not.

Sorting by NAME cannot pack a string into that key, so it uses a rank instead, by one of two
routes depending on how much there is to sort:

  * up to NAME_SORT_DIRECT matches -- which is almost every search that has any filter set at
    all -- a plain comparator over the lowercased names. Nothing is retained.
  * more than that, a one-off rank of the entire catalogue (nameOrder[row] = its position in
    A-Z order) is built once and then reused for the rest of the session. It costs one big
    sort and ~370 KB, and it is what stops "sort the whole 46,098-row table by name" from
    being a fresh half-second stall every time the filters change.
------------------------------------------------------------------------------------------]]

ItemBrowserSearch = {}

local S = ItemBrowserSearch
local D = ItemBrowserData

local floor, find, lower, sort = math.floor, string.find, string.lower, table.sort

local MAX_RANKED = 5000        -- name matches kept for ranking; beyond this we only count
local MIN_QUERY = 2            -- below this a name query matches half the table
local NAME_SORT_DIRECT = 4000  -- above this, A-Z uses the cached whole-catalogue rank

-- Sort key = (tier * 256 + nameLength) * KEY_ROW + rowIndex, one number, so table.sort uses
-- its built-in numeric comparator instead of calling back into Lua 46k*log(46k) times.
-- rowIndex must fit under KEY_ROW; 2^20 is 1,048,576 against 46,098 rows.
local KEY_ROW = 1048576
local MAX_NAME_LEN = 255

-- Field extraction, mirroring Data.lua's divisors. Pulled into locals at file scope so the
-- scan loop's upvalue lookups are as cheap as Lua makes them.
local DIV = D.DIV
local W_QUALITY               = DIV.quality[2]    -- quality is the low field: m % W_QUALITY
local D_INVTYPE, W_INVTYPE    = DIV.invtype[1],   DIV.invtype[2]
local D_CLASS                 = DIV.class[1]
local D_REQLEVEL, W_REQLEVEL  = DIV.reqlevel[1],  DIV.reqlevel[2]
local D_ITEMLVL,  W_ITEMLVL   = DIV.itemlevel[1], DIV.itemlevel[2]
-- class and subclass are adjacent 32-wide fields, so an exact (class, subclass) test is one
-- division and one modulo against the combined 1024-wide window rather than two of each.
local W_CLASSPAIR = 1024

-- Lowercased names, built lazily and incrementally.
-- Not shipped: it would double the addon's disk size for something string.lower reproduces in
-- about 30 ms. Not rebuilt per search either: that would be 46k string allocations on every
-- keystroke, which is what makes naive browsers stutter. Built in the same per-frame budget
-- the scan uses, so even the very first keystroke never blocks.
local lowerName = {}
local lowerBuilt = 0

-- row index -> its position in A-Z order, built at most once per session. See the header.
local nameOrder = nil


-- =========================================================================================
-- the sort orders
-- =========================================================================================

--- The orders the list can be in. `field` is what the key is built from; `limit` is one past
--- that field's largest possible value, which is what turns an ascending key into a
--- descending one. Order here is the order the Sort menu offers them in.
--
-- "match" is not a field: with a name typed it means the relevance tiering described in the
-- header, and with nothing typed there is nothing to rank, so it means ascending item id --
-- which is the order the arrays are already in and therefore free.
ItemBrowserSearch.orders = {
    { key = "match",   label = "Best match",    both = false },
    { key = "ilvl",    label = "Item level",    field = "itemlevel", limit = W_ITEMLVL },
    { key = "req",     label = "Required level", field = "reqlevel", limit = W_REQLEVEL },
    { key = "quality", label = "Quality",       field = "quality",   limit = W_QUALITY },
    -- Sorting by slot sorts by InventoryType, which is head-first and relic-last: the order
    -- the character pane lays its own slots out in, not alphabetical order.
    { key = "slot",    label = "Slot",          field = "invtype",   limit = W_INVTYPE },
    { key = "name",    label = "Name",          field = "name" },
    { key = "id",      label = "Item ID",       field = "id" },
}

local ORDER = {}
for i = 1, #ItemBrowserSearch.orders do
    ORDER[ItemBrowserSearch.orders[i].key] = ItemBrowserSearch.orders[i]
end

function ItemBrowserSearch:Order(key)
    return ORDER[key] or ORDER.match
end

--- nameOrder, built once. Needs the lowercase index finished, which Step() guarantees.
local function BuildNameOrder()
    local names = lowerName
    local index = {}
    for i = 1, D.rows do index[i] = i end
    sort(index, function(a, b)
        local na, nb = names[a], names[b]
        -- Equal names are not rare (the same item id range holds several "Fishing Pole"), so
        -- the tiebreak has to be here as well; without it table.sort's order for equal keys
        -- is unspecified and the list would reshuffle between identical searches.
        if na == nb then return a < b end
        return na < nb
    end)
    local rank = {}
    for position = 1, #index do rank[index[position]] = position end
    nameOrder = rank
end

--- Put job.out (row indices) into the requested order. One table.sort, always numeric except
--- for the small-result name case.
local function ApplySort(job)
    local out, n, desc = job.out, job.n, job.desc
    local order = ORDER[job.sort] or ORDER.match

    if order.key == "match" or order.field == "id" then
        -- Nothing to do: "Item ID" is the order the arrays are already in and the scan
        -- appended in, and "Best match" has either just been ranked or means the same thing.
        -- Reversing in place is the whole cost of the descending version.
        if desc then
            for i = 1, floor(n / 2) do out[i], out[n + 1 - i] = out[n + 1 - i], out[i] end
        end
        return
    end

    if order.field == "name" then
        if n <= NAME_SORT_DIRECT then
            local names = lowerName
            if desc then
                sort(out, function(a, b)
                    local na, nb = names[a], names[b]
                    if na == nb then return a < b end
                    return na > nb
                end)
            else
                sort(out, function(a, b)
                    local na, nb = names[a], names[b]
                    if na == nb then return a < b end
                    return na < nb
                end)
            end
            return
        end
        if not nameOrder then BuildNameOrder() end
        local rank, limit = nameOrder, D.rows + 1
        for i = 1, n do
            local row = out[i]
            local value = rank[row]
            if desc then value = limit - value end
            out[i] = value * KEY_ROW + row
        end
        sort(out)
        for i = 1, n do out[i] = out[i] % KEY_ROW end
        return
    end

    -- The numeric fields: one arithmetic pull out of the packed record per row, then one
    -- numeric sort.
    local packed = D.packed
    local divisor, width, limit = 1, W_QUALITY, order.limit
    if order.field == "itemlevel" then
        divisor, width = D_ITEMLVL, W_ITEMLVL
    elseif order.field == "reqlevel" then
        divisor, width = D_REQLEVEL, W_REQLEVEL
    elseif order.field == "invtype" then
        divisor, width = D_INVTYPE, W_INVTYPE
    end
    for i = 1, n do
        local row = out[i]
        local value = floor(packed[row] / divisor) % width
        if desc then value = limit - value end
        out[i] = value * KEY_ROW + row
    end
    sort(out)
    for i = 1, n do out[i] = out[i] % KEY_ROW end
end


-- =========================================================================================
-- who is asking: the Usable filter's view of the player
-- =========================================================================================

--- Bit `id` (1-based) of a class/race mask, without the bit library.
-- A mask of -1 means "everyone" and is the common case; item_template stores no other
-- negative. Masks are at most 18 bits and the probe is at most bit 11, so plain division is
-- exact in a double and needs no 32-bit wraparound reasoning.
local function MaskHas(mask, bitValue)
    if mask < 0 then return true end
    return floor(mask / bitValue) % 2 == 1
end

--- The player's skill lines by name, or nil if they cannot be read reliably.
-- GetNumSkillLines() counts only the lines the skill pane is currently showing, so a collapsed
-- header hides its children. Rather than guess -- and wrongly hide every plate item from a
-- warrior whose "Armor Proficiencies" header happens to be collapsed -- an incomplete list is
-- reported as nil and the skill half of the Usable test is skipped entirely. Absence of
-- evidence never removes a row.
local function PlayerSkills()
    if not GetNumSkillLines or not GetSkillLineInfo then return nil end
    local count = GetNumSkillLines()
    if not count or count == 0 then return nil end
    local known = {}
    for i = 1, count do
        local name, isHeader, isExpanded, rank = GetSkillLineInfo(i)
        if isHeader then
            if not isExpanded then return nil end
        elseif name then
            known[name] = rank or 0
        end
    end
    return known
end

--- Everything the Usable test needs, gathered once per search rather than once per row.
local function PlayerContext()
    -- UnitClass's second return is "WARRIOR"; UnitRace's is "Scourge". Both tables are keyed
    -- upper-case so neither side's capitalisation matters. An unknown token leaves the
    -- corresponding bit nil, which makes that half of the test a no-op rather than a filter
    -- that hides everything.
    local _, classToken = UnitClass("player")
    local _, raceToken = UnitRace("player")
    local classId = D.classBit[string.upper(classToken or "")] or 0
    local raceId = D.raceBit[string.upper(raceToken or "")] or 0
    return {
        level    = UnitLevel("player") or 1,
        classBit = classId > 0 and (2 ^ (classId - 1)) or nil,
        raceBit  = raceId > 0 and (2 ^ (raceId - 1)) or nil,
        skills   = PlayerSkills(),
    }
end

--- Would Player::CanUseItem let this character use this row?
-- Mirrors AuctionHouseUsablePlayerInfo::PlayerCanUseItem
-- (.work/ac-src/src/server/game/AuctionHouse/AuctionHouseSearcher.cpp:663) in the same order,
-- minus its RequiredSpell clause: 3.3.5 gives an addon no way to ask whether the player knows
-- an arbitrary spell id, so the 120 items that carry one are treated as usable. They are
-- recipes you already know, which the auction house would have hidden.
local function CanUse(ctx, index, class, subclass, reqLevel)
    if ctx.level < reqLevel then return false end

    local byClass = D.profSkill[class]
    local skill = byClass and byClass[subclass]
    if skill then
        local skillName = D.skillName[skill]
        if skillName == false then return false end
        if skillName and ctx.skills and not ctx.skills[skillName] then return false end
    end

    local allowClass, allowRace, reqSkill, reqRank = D:Restriction(index)
    if ctx.classBit and not MaskHas(allowClass, ctx.classBit) then return false end
    if ctx.raceBit and not MaskHas(allowRace, ctx.raceBit) then return false end

    if reqSkill ~= 0 then
        -- `false` means SkillLine.dbc has no such line, so no character anywhere has it.
        local skillName = D.skillName[reqSkill]
        if skillName == false then return false end
        if skillName and ctx.skills then
            local have = ctx.skills[skillName]
            if not have or have < reqRank then return false end
        end
    end
    return true
end


-- =========================================================================================
-- the job
-- =========================================================================================

--- True if `haystack` has a WORD starting with `needle` (both already lowercase).
-- Anchors on a space, so "cloth" hits "Linen Cloth" at tier 4 but "othe" does not.
local function WordPrefix(haystack, needle)
    if string.sub(haystack, 1, #needle) == needle then return true end
    return find(haystack, " " .. needle, 1, true) ~= nil
end

local EMPTY = {}

--- Start a search. Cheap: it validates the filter and sets up state, and scans nothing.
-- @param filter table -- text, class, subclass, slots, minQuality, minLevel, maxLevel,
--                        minItemLevel, maxItemLevel, usable, sort, sortDesc. All optional.
--                        `slots` is a SET: { [InventoryType] = true, ... }.
function ItemBrowserSearch:Begin(filter)
    filter = filter or EMPTY
    local text = filter.text or ""
    local query = lower(string.gsub(text, "^%s*(.-)%s*$", "%1"))
    local asId = tonumber(query)
    local note = nil

    -- A too-short name is IGNORED rather than fatal: with a category and a level range set,
    -- refusing to run because the name box holds one letter would throw away the filters the
    -- user actually built.
    if query ~= "" and #query < MIN_QUERY and not asId then
        query, note = "", "Type at least " .. MIN_QUERY .. " characters to search by name."
    end

    local classPair = nil
    if filter.class then
        classPair = filter.class + (filter.subclass or 0) * 32
    end

    -- An empty slot set would match nothing, which is never what "no slot chosen" means.
    local slots = filter.slots
    if slots and next(slots) == nil then slots = nil end

    local order = ORDER[filter.sort] or ORDER.match

    self.job = {
        query      = query ~= "" and query or nil,
        asId       = asId,
        idRow      = nil,
        classPair  = filter.subclass and classPair or nil,
        classOnly  = (filter.class and not filter.subclass) and filter.class or nil,
        slots      = slots,
        minQuality = filter.minQuality or 0,
        minLevel   = filter.minLevel,
        maxLevel   = filter.maxLevel,
        minIlvl    = filter.minItemLevel,
        maxIlvl    = filter.maxItemLevel,
        ctx        = filter.usable and PlayerContext() or nil,
        sort       = order.key,
        desc       = filter.sortDesc and true or false,
        note       = note,

        phase   = "index",
        cursor  = 0,
        out     = {},
        n       = 0,
        matched = 0,
        capped  = false,
    }

    if not D:IsLoaded() then
        self.job.phase = "done"
        self.job.note = "Item database not loaded -- run tools/regen.sh and reinstall the addon."
    end
    return self.job
end

--- Build the lowercase name index, at most `budget` names at a time.
-- @return rows consumed
local function StepIndex(budget)
    local total = D.rows
    if lowerBuilt >= total then return 0 end
    local last = lowerBuilt + budget
    if last > total then last = total end
    local src = D.name
    for i = lowerBuilt + 1, last do
        lowerName[i] = lower(src[i])
    end
    local consumed = last - lowerBuilt
    lowerBuilt = last
    return consumed
end

--- Advance the current job by at most `budget` rows of work.
-- @return done -- true once Results() is meaningful
function ItemBrowserSearch:Step(budget)
    local job = self.job
    if not job or job.phase == "done" then return true end

    if job.phase == "index" then
        -- The lowercase index is needed by a name query AND by A-Z ordering, and both want
        -- it complete before anything else happens.
        if job.query or job.sort == "name" then
            local used = StepIndex(budget)
            if lowerBuilt < D.rows then return false end
            budget = budget - used
            if budget <= 0 then return false end
        end
        -- Tier 1: the literal id. One binary search, so an exact id always wins even when the
        -- same digits appear inside 300 item names.
        if job.asId then
            local index = D:Find(job.asId)
            if index and self:Passes(job, index) then
                job.idRow = index
                job.matched = 1
                job.n = 1
                job.out[1] = (1 * 256) * KEY_ROW + index
            end
        end
        job.phase = "scan"
    end

    if job.phase == "scan" then
        local last = job.cursor + budget
        local total = D.rows
        if last > total then last = total end
        self:Scan(job, job.cursor + 1, last)
        job.cursor = last
        if last < total then return false end
        job.phase = "rank"
    end

    if job.phase == "rank" then
        local out = job.out
        if job.query then
            -- With a name typed, out[] holds packed relevance keys. They are only worth
            -- sorting when relevance is the requested order; either way they have to be
            -- reduced back to plain row indices before anything else touches them.
            if job.sort == "match" then sort(out) end
            for i = 1, job.n do
                out[i] = out[i] % KEY_ROW
            end
        end
        ApplySort(job)
        job.phase = "done"
    end
    return true
end

--- Do all the non-name filters admit this row? Used for the id tier and by the scan.
function ItemBrowserSearch:Passes(job, index)
    local m = D.packed[index]
    if not m then return false end
    if job.classPair and floor(m / D_CLASS) % W_CLASSPAIR ~= job.classPair then return false end
    if job.classOnly and floor(m / D_CLASS) % 32 ~= job.classOnly then return false end
    if job.slots and not job.slots[floor(m / D_INVTYPE) % W_INVTYPE] then return false end
    if m % W_QUALITY < job.minQuality then return false end
    local reqLevel = floor(m / D_REQLEVEL) % W_REQLEVEL
    if job.minLevel and reqLevel < job.minLevel then return false end
    if job.maxLevel and reqLevel > job.maxLevel then return false end
    local itemLevel = floor(m / D_ITEMLVL) % W_ITEMLVL
    if job.minIlvl and itemLevel < job.minIlvl then return false end
    if job.maxIlvl and itemLevel > job.maxIlvl then return false end
    if job.ctx then
        local class = floor(m / D_CLASS) % 32
        local subclass = floor(m / (D_CLASS * 32)) % 32
        if not CanUse(job.ctx, index, class, subclass, reqLevel) then return false end
    end
    return true
end

--- The hot loop. Everything it touches is a local; nothing in it allocates unless a row
--- actually matches, and then it appends exactly one number.
function ItemBrowserSearch:Scan(job, first, last)
    local packed = D.packed
    local names = lowerName
    local query = job.query
    local qlen = query and #query or 0
    local idRow = job.idRow
    local ctx = job.ctx
    local classPair, classOnly, slots = job.classPair, job.classOnly, job.slots
    local minQuality = job.minQuality
    local minLevel, maxLevel = job.minLevel, job.maxLevel
    local minIlvl, maxIlvl = job.minIlvl, job.maxIlvl
    local out, n, matched = job.out, job.n, job.matched

    for i = first, last do
        local m = packed[i]
        local ok = i ~= idRow
        if ok and classPair then
            ok = floor(m / D_CLASS) % W_CLASSPAIR == classPair
        elseif ok and classOnly then
            ok = floor(m / D_CLASS) % 32 == classOnly
        end
        if ok and slots then
            -- One table lookup, and only for rows the category test already let through.
            ok = slots[floor(m / D_INVTYPE) % W_INVTYPE] == true
        end
        if ok and minQuality > 0 then
            ok = m % W_QUALITY >= minQuality
        end
        local reqLevel
        if ok and (minLevel or maxLevel or ctx) then
            reqLevel = floor(m / D_REQLEVEL) % W_REQLEVEL
            if minLevel and reqLevel < minLevel then ok = false end
            if ok and maxLevel and reqLevel > maxLevel then ok = false end
        end
        if ok and (minIlvl or maxIlvl) then
            local itemLevel = floor(m / D_ITEMLVL) % W_ITEMLVL
            if minIlvl and itemLevel < minIlvl then ok = false end
            if ok and maxIlvl and itemLevel > maxIlvl then ok = false end
        end
        if ok and ctx then
            local class = floor(m / D_CLASS) % 32
            local subclass = floor(m / (D_CLASS * 32)) % 32
            ok = CanUse(ctx, i, class, subclass, reqLevel)
        end

        if ok then
            if query then
                -- string.find is the expensive one, which is why it runs last: by here the
                -- numeric filters have already thrown away everything they can.
                local name = names[i]
                local at = find(name, query, 1, true)
                if at then
                    matched = matched + 1
                    if n < MAX_RANKED then
                        local tier
                        if #name == qlen then
                            tier = 2
                        elseif at == 1 then
                            tier = 3
                        elseif WordPrefix(name, query) then
                            tier = 4
                        else
                            tier = 5
                        end
                        local len = #name
                        if len > MAX_NAME_LEN then len = MAX_NAME_LEN end
                        n = n + 1
                        out[n] = (tier * 256 + len) * KEY_ROW + i
                    else
                        job.capped = true
                    end
                end
            else
                -- No name typed: no ranking, no cap. entry[] is ascending, so appending in
                -- scan order already produces "sorted by item id".
                matched = matched + 1
                n = n + 1
                out[n] = i
            end
        end
    end

    job.n, job.matched = n, matched
end

--- @return results (array of row indices), shown, matched, capped, note
function ItemBrowserSearch:Results()
    local job = self.job
    if not job then return EMPTY, 0, 0, false, nil end
    return job.out, job.n, job.matched, job.capped, job.note
end

--- 0..1, for a progress line while a big scan settles.
function ItemBrowserSearch:Progress()
    local job = self.job
    if not job then return 1 end
    if job.phase == "done" then return 1 end
    if job.phase == "index" then return (lowerBuilt / (D.rows * 2)) end
    return 0.5 + (job.cursor / (D.rows * 2))
end

--- Run a whole search now. Used by the test harness and anywhere a frame budget is pointless.
function ItemBrowserSearch:Run(filter)
    self:Begin(filter)
    while not self:Step(1000000) do end
    return self:Results()
end

--- Spend idle time on the lowercase index so the first keystroke does not have to.
function ItemBrowserSearch:Prime(budget)
    return StepIndex(budget) == 0
end

function ItemBrowserSearch:MaxRanked()
    return MAX_RANKED
end
