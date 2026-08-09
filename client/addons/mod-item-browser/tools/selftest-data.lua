--[[----------------------------------------------------------------------------------------
ItemBrowser self-test, part 1: the shipped database and the filters.

    tools/selftest.sh                            dump the rows and run both parts
    luajit tools/selftest-data.lua <rows.tsv>    just this part

Loads the generated Data/ plus the hand-written Data.lua and Search.lua under a Lua 5.1
interpreter with a stub FrameXML, and checks them against a fresh dump of
acore_world.item_template (itemdb.py --dump-rows, whose SELECT deliberately lists the columns
in a DIFFERENT order from the generator's -- a harness that reads the same tuple the same way
cannot catch a column being written into the wrong field).

What it proves that the generator's own invariants cannot: the invariants check the emitted
BYTES, this checks what the addon's accessors give back after the client has parsed them.

The Usable suite is checked against an independent reimplementation of
AuctionHouseUsablePlayerInfo::PlayerCanUseItem written straight off the database rows, so a
shared misreading of the rule would have to be made twice, in two different shapes, to pass.
------------------------------------------------------------------------------------------]]

local TRUTH = ...
if not TRUTH then
    io.stderr:write("usage: luajit selftest-data.lua <item_template dump.tsv>   (tools/selftest.sh makes one)\n")
    os.exit(2)
end
local ADDON = (debug.getinfo(1, "S").source:sub(2):match("(.*)/[^/]*$") or ".") .. "/../ItemBrowser"

local pass, fail = 0, 0
local function check(cond, msg)
    if cond then pass = pass + 1; print("  ok   " .. msg)
    else fail = fail + 1; print("  FAIL " .. msg) end
end

ITEM_QUALITY_COLORS = {}
for i = -1, 6 do ITEM_QUALITY_COLORS[i] = { hex = string.format("|cffCLIENT%d", i) } end
local QNAME = { [0]="Poor","Common","Uncommon","Rare","Epic","Legendary","Artifact","Heirloom" }
for q = 0, 7 do _G["ITEM_QUALITY" .. q .. "_DESC"] = QNAME[q] end

-- the player the Usable filter sees; mutated per test
PLAYER = { class = "MAGE", race = "Human", level = 80, skills = nil }
function UnitClass() return "Mage", PLAYER.class end
function UnitRace() return "Human", PLAYER.race end
function UnitLevel() return PLAYER.level end
function GetNumSkillLines()
    if not PLAYER.skills then return 0 end
    return #PLAYER.skills
end
function GetSkillLineInfo(i)
    local s = PLAYER.skills[i]
    return s[1], s[2], s[3], s[4]
end

local function run(path)
    local chunk, err = loadfile(path)
    if not chunk then error("load " .. path .. ": " .. tostring(err)) end
    chunk()
end

local t0 = os.clock()
run(ADDON .. "/Data.lua")
run(ADDON .. "/Data/Icons.lua")
run(ADDON .. "/Data/Filters.lua")
for i = 1, 8 do run(string.format("%s/Data/Items_%02d.lua", ADDON, i)) end
run(ADDON .. "/Data/Meta.lua")
local tLoad = (os.clock() - t0) * 1000
run(ADDON .. "/Search.lua")

local D, S = ItemBrowserData, ItemBrowserSearch


print(string.format("load %.0f ms | rows=%d icons=%d categories=%d restrictions=%d digest=%s",
      tLoad, D.rows, #D.iconName, #D.categoryOrder, #D.restrict / 4, D.build.digest))

-- ------------------------------------------------------------------------- ground truth
local truth = {}      -- entry -> record
local order = {}
for line in io.lines(TRUTH) do
    local f = {}
    for field in string.gmatch(line .. "\t", "([^\t]*)\t") do f[#f + 1] = field end
    local r = {
        entry = tonumber(f[1]), class = tonumber(f[2]), subclass = tonumber(f[3]),
        quality = tonumber(f[4]), ilvl = tonumber(f[5]), rlvl = tonumber(f[6]),
        inv = tonumber(f[7]), allowClass = tonumber(f[8]), allowRace = tonumber(f[9]),
        reqSkill = tonumber(f[10]), reqRank = tonumber(f[11]), reqSpell = tonumber(f[12]),
        name = f[13],
    }
    truth[r.entry] = r
    order[#order + 1] = r
end
print(string.format("truth rows: %d", #order))

print("\n== 1. every row decodes back to what the database holds")
check(D.rows == #order, "row count matches item_template")
local bad, badExample = 0, nil
for i = 1, D.rows do
    local t = truth[D.entry[i]]
    local q, inv, cls, sub, rl, il = D:Decode(i)
    local ac, ar, rs, rr = D:Restriction(i)
    if not t or D.name[i] ~= t.name or q ~= t.quality or inv ~= t.inv or cls ~= t.class
       or sub ~= t.subclass or rl ~= t.rlvl or il ~= t.ilvl
       or ac ~= t.allowClass or ar ~= t.allowRace or rs ~= t.reqSkill or rr ~= t.reqRank then
        bad = bad + 1
        badExample = badExample or string.format("entry %d", D.entry[i])
    end
end
check(bad == 0, string.format("all %d rows round-trip (name, quality, invtype, class, "
      .. "subclass, req level, item level, allowable class/race, required skill/rank)%s",
      D.rows, bad > 0 and (" -- " .. bad .. " wrong, e.g. " .. badExample) or ""))

print("\n== 2. category labels come out of the DBCs the way the AH shows them")
local function label(entry)
    local i = D:Find(entry)
    local _, _, cls, sub = D:Decode(i)
    return D:CategoryLabel(cls, sub)
end
local c, s = label(49623); check(c == "Weapon" and s == "Two-Handed Axes",
    "49623 Shadowmourne -> " .. tostring(c) .. " / " .. tostring(s))
c, s = label(51220); check(c == "Armor" and s == "Plate",
    "51220 Sanctified Ymirjar Lord's Breastplate -> " .. tostring(c) .. " / " .. tostring(s))
c, s = label(39); check(c == "Armor" and s == "Cloth",
    "39 Recruit's Pants (grey) -> " .. tostring(c) .. " / " .. tostring(s))
c, s = label(6948); check(c == "Miscellaneous" and s == "Junk",
    "6948 Hearthstone -> " .. tostring(c) .. " / " .. tostring(s))
c, s = label(2589); check(c == "Trade Goods" and s == "Cloth",
    "2589 Linen Cloth -> " .. tostring(c) .. " / " .. tostring(s))
-- the whole point of preferring VerboseName: DisplayName says "Axe" for both
local weapon = D.category[2]
local axes = {}
for i = 1, #weapon.sub do
    if weapon.sub[i][1] == 0 or weapon.sub[i][1] == 1 then axes[#axes + 1] = weapon.sub[i][3] end
end
check(axes[1] == "One-Handed Axes" and axes[2] == "Two-Handed Axes",
      "weapon subclasses 0 and 1 are distinguishable: " .. table.concat(axes, " / "))
local labelled = 0
for i = 1, #D.categoryOrder do
    local cat = D.category[D.categoryOrder[i]]
    labelled = labelled + #cat.sub
end
check(labelled == 113, "every (class, subclass) pair in the data has a label: " .. labelled)

print("\n== 3. quality colours")
check(D:QualityHex(4) == "|cffa335ee" or D:QualityHex(4) == "|cffCLIENT4",
      "epic uses the client's colour when there is one: " .. D:QualityHex(4))
check(D:QualityHex(7) == "|cffe6cc80",
      "heirloom falls back to the published palette (ITEM_QUALITY_COLORS stops at 6): "
      .. D:QualityHex(7))
check(select(1, D:ColouredName(D:Find(49623))) == D:QualityHex(5) .. "Shadowmourne|r",
      "Shadowmourne is coloured legendary")

-- --------------------------------------------------------- a reference PlayerCanUseItem
-- Independent reimplementation of AuctionHouseSearcher.cpp:663 straight off the truth rows,
-- used to check the addon's version rather than to define it.
local WEAPON_SKILL = { [0]=44,[1]=172,[2]=45,[3]=46,[4]=54,[5]=160,[6]=229,[7]=43,[8]=55,
                       [10]=136,[13]=473,[15]=173,[16]=176,[17]=253,[18]=226,[19]=228,[20]=356 }
local ARMOR_SKILL = { [1]=415,[2]=414,[3]=413,[4]=293,[6]=433 }
local function refCanUse(t, ctx)
    local skill = (t.class == 2 and WEAPON_SKILL[t.subclass])
               or (t.class == 4 and ARMOR_SKILL[t.subclass]) or nil
    if skill and (ctx.skills[skill] or 0) == 0 then return false end
    if t.allowClass >= 0 and math.floor(t.allowClass / ctx.classBit) % 2 == 0 then return false end
    if t.allowRace >= 0 and math.floor(t.allowRace / ctx.raceBit) % 2 == 0 then return false end
    if t.reqSkill ~= 0 then
        local have = ctx.skills[t.reqSkill] or 0
        if have == 0 or have < t.reqRank then return false end
    end
    if ctx.level < t.rlvl then return false end
    return true
end

print("\n== 4. filters agree with a direct pass over the database rows")
local function refCount(pred)
    local n = 0
    for i = 1, #order do if pred(order[i]) then n = n + 1 end end
    return n
end
local function runFilter(filter)
    local _, n, matched = S:Run(filter)
    return n, matched
end

local cases = {
    { "no filter at all",
      {}, function() return true end },
    { "category = Armor",
      { class = 4 }, function(t) return t.class == 4 end },
    { "category = Armor / Plate",
      { class = 4, subclass = 4 }, function(t) return t.class == 4 and t.subclass == 4 end },
    { "category = Weapon / Two-Handed Axes",
      { class = 2, subclass = 1 }, function(t) return t.class == 2 and t.subclass == 1 end },
    { "quality >= Epic",
      { minQuality = 4 }, function(t) return t.quality >= 4 end },
    { "quality >= Epic, category = Armor / Plate",
      { class = 4, subclass = 4, minQuality = 4 },
      function(t) return t.quality >= 4 and t.class == 4 and t.subclass == 4 end },
    { "required level 70..80",
      { minLevel = 70, maxLevel = 80 },
      function(t) return t.rlvl >= 70 and t.rlvl <= 80 end },
    { "item level 200..277",
      { minItemLevel = 200, maxItemLevel = 277 },
      function(t) return t.ilvl >= 200 and t.ilvl <= 277 end },
    { "required level 80 AND item level 226..284 AND quality >= Epic",
      { minLevel = 80, maxLevel = 80, minItemLevel = 226, maxItemLevel = 284, minQuality = 4 },
      function(t) return t.rlvl == 80 and t.ilvl >= 226 and t.ilvl <= 284 and t.quality >= 4 end },
    { "everything at once (Armor/Plate, epic+, level 80, ilvl 200..300)",
      { class = 4, subclass = 4, minQuality = 4, minLevel = 80, maxLevel = 80,
        minItemLevel = 200, maxItemLevel = 300 },
      function(t) return t.class == 4 and t.subclass == 4 and t.quality >= 4
                  and t.rlvl == 80 and t.ilvl >= 200 and t.ilvl <= 300 end },
}
for _, case in ipairs(cases) do
    local got, matched = runFilter(case[2])
    local want = refCount(case[3])
    check(got == want and matched == want,
          string.format("%-58s %d rows", case[1], want)
          .. (got == want and "" or ("  (got " .. got .. "/" .. matched .. ")")))
end

print("\n== 5. the Usable filter matches PlayerCanUseItem")
-- Two characters, built as the client would report them: a level-80 human mage with cloth
-- only, and a level-80 orc warrior with the full plate/weapon set.
local SKILLNAME = {}
for id, n in pairs(D.skillName) do if n then SKILLNAME[id] = n end end
local function lines(byId)
    local out = { { "Armor Proficiencies", true, true, 0 } }
    for id, rank in pairs(byId) do
        out[#out + 1] = { SKILLNAME[id] or ("skill" .. id), false, false, rank }
    end
    return out
end
local characters = {
    { name = "level 80 human mage, cloth only", class = "MAGE", race = "Human", level = 80,
      classBit = 2 ^ (8 - 1), raceBit = 2 ^ (1 - 1), skills = { [415] = 1 } },
    { name = "level 80 orc warrior, all armour and weapons", class = "WARRIOR", race = "Orc",
      level = 80, classBit = 2 ^ (1 - 1), raceBit = 2 ^ (2 - 1),
      skills = { [415]=1,[414]=1,[413]=1,[293]=1,[433]=1,[43]=1,[44]=1,[54]=1,[55]=1,
                 [160]=1,[172]=1,[173]=1,[136]=1,[229]=1,[473]=1,[176]=1,[45]=1,[46]=1,
                 [226]=1,[164]=350 } },
    { name = "level 10 human mage, cloth only", class = "MAGE", race = "Human", level = 10,
      classBit = 2 ^ (8 - 1), raceBit = 2 ^ (1 - 1), skills = { [415] = 1 } },
}
for _, ch in ipairs(characters) do
    PLAYER.class, PLAYER.race, PLAYER.level = ch.class, ch.race, ch.level
    PLAYER.skills = lines(ch.skills)
    local got = select(2, S:Run({ usable = true }))
    local want = refCount(function(t) return refCanUse(t, ch) end)
    check(got == want, string.format("%-46s %d usable items", ch.name, want)
          .. (got == want and "" or ("  (got " .. got .. ")")))
end
-- and the safety valve: an unreadable skill list must not remove rows
PLAYER.class, PLAYER.race, PLAYER.level = "MAGE", "Human", 80
PLAYER.skills = nil
local noSkills = select(2, S:Run({ usable = true }))
local withSkills = (function()
    PLAYER.skills = lines(characters[1].skills)
    return select(2, S:Run({ usable = true }))
end)()
-- the enumeration is also refused when any header is collapsed
PLAYER.skills = { { "Armor Proficiencies", true, false, 0 }, { "Cloth", false, false, 1 } }
local collapsed = select(2, S:Run({ usable = true }))
check(collapsed == noSkills,
      "a collapsed skill header is treated the same way: " .. collapsed .. " rows")
check(noSkills > withSkills,
      string.format("an unreadable skill list is permissive, not restrictive: %d >= %d",
                    noSkills, withSkills))
PLAYER.class, PLAYER.race, PLAYER.level, PLAYER.skills = "MAGE", "Human", 80, nil

print("\n== 6. name search and ranking")
local function firstNames(filter, n)
    local res, shown = S:Run(filter)
    local out = {}
    for i = 1, math.min(n, shown) do out[i] = D.name[res[i]] end
    return out, shown
end
-- Tiering, not raw substring order, is the thing being tested: everything whose name STARTS
-- with "linen" must come before "Bolt of Linen Cloth", and within that tier the shortest name
-- wins, so "Linen Bag" legitimately outranks "Linen Cloth".
local names, shown = firstNames({ text = "linen" }, 8)
local prefixed = true
for i = 1, 5 do
    if string.sub(string.lower(names[i]), 1, 5) ~= "linen" then prefixed = false end
end
local boltAt = nil
for i = 1, #names do if names[i] == "Bolt of Linen Cloth" then boltAt = i end end
check(prefixed and names[1] == "Linen Bag" and boltAt == nil,
      "\"linen\" puts prefix matches first and Bolt of Linen Cloth nowhere near the top "
      .. "(of " .. shown .. "): " .. table.concat(names, ", "))
names = firstNames({ text = "linen b" }, 1)
check(names[1] == "Linen Bag", "\"linen b\" -> " .. tostring(names[1]))
names = firstNames({ text = "bolt of linen" }, 1)
check(names[1] == "Bolt of Linen Cloth", "\"bolt of linen\" -> " .. tostring(names[1]))
names = firstNames({ text = "hearthstone" }, 1)
check(names[1] == "Hearthstone", "\"hearthstone\" -> " .. tostring(names[1]))
names = firstNames({ text = "6948" }, 1)
check(names[1] == "Hearthstone", "\"6948\" (an id) -> " .. tostring(names[1]))
names = firstNames({ text = "shadowmourne" }, 1)
check(names[1] == "Shadowmourne", "\"shadowmourne\" -> " .. tostring(names[1]))
-- text combined with the filter bar
local _, n1 = S:Run({ text = "cloth" })
local _, n2 = S:Run({ text = "cloth", class = 4 })
local want = refCount(function(t)
    return t.class == 4 and string.find(string.lower(t.name), "cloth", 1, true) ~= nil
end)
check(n2 == want, string.format("\"cloth\" + category Armor: %d of %d name matches", want, n1))
local _, tooShort, note = nil, nil, nil
local r, sh, m, capped, nt = S:Run({ text = "a", class = 3 })
check(sh == D.category[3].count and nt ~= nil,
      "a one-character name is ignored, the category still applies (" .. sh .. " gems), and "
      .. "the reason is reported: " .. tostring(nt))
local res, shown2, matched2, capped2 = S:Run({ text = "e" .. "" })
res, shown2, matched2, capped2 = S:Run({ text = "of" })
check(matched2 > shown2 == capped2, string.format(
      "\"of\" matches %d, keeps %d, capped=%s", matched2, shown2, tostring(capped2)))

print("\n== 7. an id that is also a substring is not listed twice")
local res7, shown7 = S:Run({ text = "2589" })
local seen, dupes = {}, 0
for i = 1, shown7 do
    if seen[res7[i]] then dupes = dupes + 1 end
    seen[res7[i]] = true
end
check(dupes == 0 and D.name[res7[1]] == "Linen Cloth",
      "\"2589\" -> " .. D.name[res7[1]] .. ", " .. shown7 .. " rows, " .. dupes .. " duplicates")

print("\n== 8. chunked stepping gives exactly the same answer as one pass")
local function chunked(filter, budget)
    S:Begin(filter)
    local steps = 0
    while not S:Step(budget) do steps = steps + 1 end
    local out, n = S:Results()
    local copy = {}
    for i = 1, n do copy[i] = out[i] end
    return copy, n, steps
end
for _, filter in ipairs({ {}, { class = 4, minQuality = 3 }, { text = "cloth" },
                          { text = "of", minLevel = 60 } }) do
    local a, na = chunked(filter, 1000000)
    local b, nb, steps = chunked(filter, 977)      -- deliberately not a divisor of 46098
    local same = na == nb
    if same then for i = 1, na do if a[i] ~= b[i] then same = false break end end end
    check(same, string.format("identical over %d steps of 977 rows (%d results)", steps, na))
end

print("\n== 9. the slot tier is what item_template's InventoryType says it is")
-- Every (class, subclass, InventoryType) triple in the database must appear in the generated
-- slot lists with the right count, and the counts under a subclass must add up to it. That is
-- what makes the tree's third tier trustworthy: a slot that went missing here would silently
-- hide items behind a branch that looks complete.
local triples = {}
for i = 1, #order do
    local t = order[i]
    local key = t.class .. ":" .. t.subclass .. ":" .. t.inv
    triples[key] = (triples[key] or 0) + 1
end
local emittedTriples, slotProblem = 0, nil
for c = 1, #D.categoryOrder do
    local cls = D.categoryOrder[c]
    local cat = D.category[cls]
    for s = 1, #cat.sub do
        local subEntry = cat.sub[s]
        local slots = subEntry[4]
        local total = 0
        for i = 1, #slots - 1, 2 do
            local key = cls .. ":" .. subEntry[1] .. ":" .. slots[i]
            if triples[key] ~= slots[i + 1] then
                slotProblem = slotProblem or (key .. " emitted " .. slots[i + 1] ..
                                              ", database has " .. tostring(triples[key]))
            end
            total = total + slots[i + 1]
            emittedTriples = emittedTriples + 1
        end
        if total ~= subEntry[2] then
            slotProblem = slotProblem or string.format("class %d subclass %d: slots sum to %d, "
                          .. "subclass holds %d", cls, subEntry[1], total, subEntry[2])
        end
    end
end
check(slotProblem == nil and emittedTriples == 247,
      "all " .. emittedTriples .. " class/subclass/slot triples match the database"
      .. (slotProblem and (" -- " .. slotProblem) or ""))

local noToken = 0
for i = 1, D.rows do
    local _, inv = D:Decode(i)
    if inv ~= 0 and not D.slotToken[inv] then noToken = noToken + 1 end
end
check(noToken == 0, "every equippable row's InventoryType resolves to a slot token")
check(D.slotToken[15] == "RANGED" and D.slotToken[26] == "RANGEDRIGHT"
      and D.slotToken[5] == "CHEST" and D.slotToken[20] == "ROBE",
      "the tokens are the client's global names, duplicates and all")
check(D.limits.reqLevel == 100 and D.limits.itemLevel == 435,
      string.format("the slider bounds are the live maxima: required %d, item level %d",
                    D.limits.reqLevel, D.limits.itemLevel))

print("\n== 10. filtering by an inventory slot")
local slotCases = {
    { "Weapon / Bows, slot Ranged (both ranged ids)",
      { class = 2, subclass = 2, slots = { [15] = true, [26] = true } },
      function(t) return t.class == 2 and t.subclass == 2
                  and (t.inv == 15 or t.inv == 26) end },
    { "Armor / Cloth, slot Head",
      { class = 4, subclass = 1, slots = { [1] = true } },
      function(t) return t.class == 4 and t.subclass == 1 and t.inv == 1 end },
    { "anything in an off hand (SHIELD and WEAPONOFFHAND)",
      { slots = { [14] = true, [22] = true } },
      function(t) return t.inv == 14 or t.inv == 22 end },
    -- The sentence this whole feature exists for, both ways round.
    { "bows, ITEM level 10-15",
      { class = 2, subclass = 2, minItemLevel = 10, maxItemLevel = 15 },
      function(t) return t.class == 2 and t.subclass == 2
                  and t.ilvl >= 10 and t.ilvl <= 15 end },
    { "bows, REQUIRED level 10-15",
      { class = 2, subclass = 2, minLevel = 10, maxLevel = 15 },
      function(t) return t.class == 2 and t.subclass == 2
                  and t.rlvl >= 10 and t.rlvl <= 15 end },
}
for _, case in ipairs(slotCases) do
    local _, got = S:Run(case[2])
    local want = refCount(case[3])
    check(got == want, string.format("%-52s %d rows", case[1], want)
          .. (got == want and "" or ("  (got " .. got .. ")")))
end
-- An empty slot set is "no slot chosen", not "match nothing" -- a UI that hands one over
-- during a rebuild must not blank the list.
check(select(2, S:Run({ class = 2, subclass = 2, slots = {} })) == 308,
      "an empty slot set filters nothing")

print("\n== 11. every sort order is a permutation, in the right order")
-- Timed here rather than in the timing block below because it can only happen once: the
-- whole-catalogue A-Z rank is built on the first name sort and reused for the session.
local tRank = os.clock()
S:Run({ sort = "name" })
print(string.format("  (first A-Z sort of all %d rows, which builds the reusable rank: %.0f ms)",
                    D.rows, (os.clock() - tRank) * 1000))
local FIELD = {
    ilvl = function(i) return select(6, D:Decode(i)) end,
    req = function(i) return select(5, D:Decode(i)) end,
    quality = function(i) return (D:Decode(i)) end,
    slot = function(i) return select(2, D:Decode(i)) end,
    id = function(i) return D.entry[i] end,
    name = function(i) return string.lower(D.name[i]) end,
}
local baseline = {}
do
    local res, n = S:Run({ class = 4, subclass = 4 })     -- Armor / Plate, 4,264 rows
    for i = 1, n do baseline[res[i]] = true end
end
for _, order in ipairs(S.orders) do
    for _, desc in ipairs({ false, true }) do
        local res, n = S:Run({ class = 4, subclass = 4, sort = order.key, sortDesc = desc })
        local seen, dupes, missing, unordered = {}, 0, 0, nil
        local field = FIELD[order.key]
        for i = 1, n do
            local row = res[i]
            if seen[row] then dupes = dupes + 1 end
            seen[row] = true
            if not baseline[row] then missing = missing + 1 end
            if field and i > 1 then
                local a, b = field(res[i - 1]), field(row)
                if desc then
                    if a < b then unordered = unordered or (tostring(a) .. " before " .. tostring(b)) end
                elseif a > b then
                    unordered = unordered or (tostring(a) .. " before " .. tostring(b))
                end
            end
        end
        local ok = (n == 4264) and dupes == 0 and missing == 0 and unordered == nil
        check(ok, string.format("%-12s %-10s %d rows, no duplicates, correctly ordered%s",
              order.label, desc and "descending" or "ascending", n,
              unordered and ("  -- " .. unordered) or ""))
    end
end
-- Sorting must never change WHICH items match, only their order.
local nameSorted = select(2, S:Run({ text = "linen", sort = "name" }))
local relevance = select(2, S:Run({ text = "linen" }))
check(nameSorted == relevance,
      "a name search keeps the same matches whichever order it is shown in: " .. relevance)
local res12 = S:Run({ text = "linen", sort = "name" })
check(D.name[res12[1]] < D.name[res12[2]],
      "and A-Z really is A-Z: " .. D.name[res12[1]] .. " before " .. D.name[res12[2]])

print("\n== 12. timing (LuaJIT; WoW's interpreter is several times slower)")
local function time(filter, label)
    S:Run(filter)                                   -- warm the lowercase index
    local t = os.clock()
    local _, n = S:Run(filter)
    print(string.format("  %-46s %6.1f ms  %d rows", label, (os.clock() - t) * 1000, n))
end
time({}, "full table, no filter")
time({ class = 4, subclass = 4 }, "one subcategory")
time({ minQuality = 4, minLevel = 70, maxLevel = 80 }, "quality + level range")
time({ text = "cloth" }, "name search")
time({ text = "er" }, "name search matching a lot (\"er\")")
time({ text = "of" }, "name search past the 5000 cap (\"of\")")
time({ usable = true }, "usable only")
-- The sorts, which are the only new per-search cost. The worst case is deliberately the one
-- measured: every row matching AND a sort over all of them.
time({ sort = "ilvl", sortDesc = true }, "full table sorted by item level")
time({ sort = "quality", sortDesc = true }, "full table sorted by quality")
time({ sort = "name" }, "full table sorted A-Z (rank already built, see 11)")
time({ class = 4, subclass = 4, sort = "ilvl", sortDesc = true }, "one subcategory by ilvl")
time({ class = 2, subclass = 2, slots = { [15] = true, [26] = true },
       minItemLevel = 10, maxItemLevel = 15 }, "bows, ranged slot, item level 10-15")


print(string.format("\n%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
