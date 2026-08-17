#!/usr/bin/env python3
"""The SHAPE of the three world-DB `*_dbc` override tables, as static data.

WHY THIS FILE EXISTS AND WHY IT IS NOT READ FROM THE DATABASE AT RUN TIME
------------------------------------------------------------------------
`DBCDatabaseLoader::Load` (src/server/shared/DataStores/DBCDatabaseLoader.cpp:124) walks the
DBC format string from `DBCfmt.h` and consumes exactly ONE sql column per format character:

    ASSERT(sqlColumnNumber == result->GetFieldCount(), "SQL format string does not match ...")

That ASSERT is a process abort during `LoadDBCStores` (World.cpp:384), i.e. worldserver never
finishes booting. So the column COUNT and ORDER of these tables are frozen by the core binary,
not by us -- they may never be ALTERed. Freezing them here as a literal makes generator
invariant #7 ("emitted column count == strlen(format string)") checkable offline, in CI, with
no database and no client, which is the whole point of `dkspells.py --check`.

`dkspells.py` re-asserts this literal against `information_schema` whenever it can reach the
live database, so the two can never silently diverge.

Regenerate (read-only) with:
    mysql -N information_schema -e "SELECT TABLE_NAME, ORDINAL_POSITION, COLUMN_NAME, \
      COLUMN_TYPE FROM COLUMNS WHERE TABLE_SCHEMA='acore_world' AND TABLE_NAME IN \
      ('spell_dbc','skilllineability_dbc','charstartoutfit_dbc') ORDER BY 1,2"

FORMAT STRING CHARACTERS (src/common/DataStores/DBCFileLoader.h:27-35)
    n  FT_IND      uint32, this is the index column, parsed into the record
    d  FT_SORT     uint32 index column, NOT copied into the record (CharStartOutfit.ID)
    i  FT_INT      uint32,  4 bytes
    f  FT_FLOAT    float,   4 bytes
    s  FT_STRING   char*,   4 bytes in the file (an offset into the string block)
    b  FT_BYTE     uint8,   1 BYTE  -- this is why record_size != field_count*4 sometimes
    x  FT_NA       4 bytes in the file, read from SQL and DISCARDED by the server
    X  FT_NA_BYTE  1 byte in the file, discarded

Two consequences that bite:
  * `x` is NOT "no column". It still consumes an SQL column (see the loop above) and it still
    occupies 4 bytes in the DBC file. All 32 Description_/AuraDescription_ locale columns of
    Spell.dbc are `x` -- they are real strings in the file that the server throws away. That is
    exactly why the tooltip can only come from the client MPQ (DESIGN.md section 2).
  * CharStartOutfit.dbc is `dbbbX...`: 77 format characters but only 296 bytes per record,
    because RaceID/ClassID/SexID/OutfitID are four single bytes packed into one DWORD. A reader
    that assumes field_count*4 == record_size silently reads garbage from it.
"""

# Column classification kinds returned by DbcTable.kind().
KIND_UINT32 = "u32"
KIND_INT32  = "i32"
KIND_UINT8  = "u8"
KIND_FLOAT  = "f"
KIND_STRING = "s"


class DbcTable:
    """One world-DB `*_dbc` override table and the DBC file it mirrors.

    `sql_table` may be None for a file the server does not load at all. Exactly one such file
    matters here -- `CharBaseInfo.dbc`, the race/class availability matrix, which has no
    `CharBaseInfofmt` in DBCfmt.h and no reference anywhere in src/. It is client-only, so it
    ships in the archive and has no SQL half; the server's equivalent gate is which
    `playercreateinfo` rows exist.

    `strings` names columns that hold a string-block offset but are NOT localized `*_Lang_*`
    slots, so `kind()` cannot derive it from the name. There are two in the whole toolkit --
    `ChrClasses.Filename` (the class token, "WARRIOR"/"DEATHKNIGHT", which FrameXML and GlueXML
    both key `CLASS_ICON_TCOORDS` and `RAID_CLASS_COLORS` on) and `TalentTab.BackgroundFile` --
    and both have to be written, not just read, so getting them wrong would put an integer where
    the client expects an offset and print garbage.
    """

    def __init__(self, sql_table, dbc_file, fmt, columns, signed, strings=()):
        assert len(columns) == len(fmt), (
            f"{sql_table or dbc_file}: {len(columns)} columns but format string is "
            f"{len(fmt)} chars")
        self.sql_table = sql_table
        self.dbc_file = dbc_file
        self.fmt = fmt
        self.columns = tuple(columns)
        self.signed = frozenset(signed)
        self.extra_strings = frozenset(strings)
        assert self.extra_strings <= set(self.columns), (
            f"{sql_table or dbc_file}: strings= names a column that does not exist: "
            f"{sorted(self.extra_strings - set(self.columns))}")
        self.index_of = {n: i for i, n in enumerate(self.columns)}
        assert len(self.index_of) == len(self.columns), f"{sql_table}: duplicate column name"
        # Byte offset of every column inside a DBC record, and the record size the format
        # string implies. FT_BYTE/FT_NA_BYTE are one byte; everything else is four.
        self.offsets = []
        off = 0
        for c in fmt:
            self.offsets.append(off)
            off += 1 if c in "bX" else 4
        self.record_size = off

    def kind(self, i):
        """How column i must be read out of the DBC and written into the SQL.

        Float-ness and string-ness are DERIVED, never listed: a column is a float iff the
        format string says `f`, and a string iff its name is a localized `*_Lang_<loc>` slot
        that is not the trailing `_Mask` bitfield. Both derivations are asserted against
        information_schema at emit time. Only signedness needs a list, because the DBC file
        does not record it and the SQL column type does.
        """
        c = self.fmt[i]
        name = self.columns[i]
        if c == "f":
            return KIND_FLOAT
        if "_Lang_" in name and not name.endswith("_Mask"):
            return KIND_STRING
        if name in self.extra_strings:
            return KIND_STRING
        if c in "bX":
            return KIND_UINT8
        return KIND_INT32 if name in self.signed else KIND_UINT32

    def string_columns(self):
        return frozenset(i for i in range(len(self.columns)) if self.kind(i) == KIND_STRING)

    def index_column(self):
        """Format index of the `n`/`d` index column. `SELECT * ... ORDER BY ID DESC` and
        DBCDatabaseLoader's index-table sizing both key on this one.

        Returns None for a file that has no index column at all. `CharBaseInfo.dbc` is the only
        one here: it is a flat list of (RaceID, ClassID) byte pairs with no key, which is why
        the client can only ask "is this pair present", never "give me row N".
        """
        for i, c in enumerate(self.fmt):
            if c in "nd":
                return i
        return None

    def __len__(self):
        return len(self.columns)


# Format strings, copied VERBATIM from the pinned core at
# src/server/shared/DataStores/DBCfmt.h lines 31, 102 and 110. If a core bump changes one of
# these, every generated row is wrong and worldserver aborts at boot -- dkspells.py diffs them
# against the checkout when --ac-src is given.
SPELL_ENTRY_FMT = (
    "niiiiiiiiiiiixixiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiifxiiiiiiiiiiiiiiiiiiiiiiiiiiii"
    "fffiiiiiiiiiiiiiiiiiiiiifffiiiiiiiiiiiiiiifffiiiiiiiiiiiiiissssssssssssssss"
    "xssssssssssssssssxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxiiiiiiiiiiixfffxxxiiiii"
    "xxfffxx"
)
SKILL_LINE_ABILITY_FMT = "niiiixxiiiiixx"
CHAR_START_OUTFIT_FMT = (
    "dbbbXiiiiiiiiiiiiiiiiiiiiiiiixxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
)

# ---- spell_dbc : 234 columns
SPELL_DBC_COLUMNS = """
ID Category DispelType Mechanic Attributes AttributesEx AttributesEx2 AttributesEx3
AttributesEx4 AttributesEx5 AttributesEx6 AttributesEx7 ShapeshiftMask unk_320_2
ShapeshiftExclude unk_320_3 Targets TargetCreatureType RequiresSpellFocus FacingCasterFlags
CasterAuraState TargetAuraState ExcludeCasterAuraState ExcludeTargetAuraState CasterAuraSpell
TargetAuraSpell ExcludeCasterAuraSpell ExcludeTargetAuraSpell CastingTimeIndex RecoveryTime
CategoryRecoveryTime InterruptFlags AuraInterruptFlags ChannelInterruptFlags ProcTypeMask
ProcChance ProcCharges MaxLevel BaseLevel SpellLevel DurationIndex PowerType ManaCost
ManaCostPerLevel ManaPerSecond ManaPerSecondPerLevel RangeIndex Speed ModalNextSpell
CumulativeAura Totem_1 Totem_2 Reagent_1 Reagent_2 Reagent_3 Reagent_4 Reagent_5 Reagent_6
Reagent_7 Reagent_8 ReagentCount_1 ReagentCount_2 ReagentCount_3 ReagentCount_4 ReagentCount_5
ReagentCount_6 ReagentCount_7 ReagentCount_8 EquippedItemClass EquippedItemSubclass
EquippedItemInvTypes Effect_1 Effect_2 Effect_3 EffectDieSides_1 EffectDieSides_2
EffectDieSides_3 EffectRealPointsPerLevel_1 EffectRealPointsPerLevel_2
EffectRealPointsPerLevel_3 EffectBasePoints_1 EffectBasePoints_2 EffectBasePoints_3
EffectMechanic_1 EffectMechanic_2 EffectMechanic_3 ImplicitTargetA_1 ImplicitTargetA_2
ImplicitTargetA_3 ImplicitTargetB_1 ImplicitTargetB_2 ImplicitTargetB_3 EffectRadiusIndex_1
EffectRadiusIndex_2 EffectRadiusIndex_3 EffectAura_1 EffectAura_2 EffectAura_3
EffectAuraPeriod_1 EffectAuraPeriod_2 EffectAuraPeriod_3 EffectMultipleValue_1
EffectMultipleValue_2 EffectMultipleValue_3 EffectChainTargets_1 EffectChainTargets_2
EffectChainTargets_3 EffectItemType_1 EffectItemType_2 EffectItemType_3 EffectMiscValue_1
EffectMiscValue_2 EffectMiscValue_3 EffectMiscValueB_1 EffectMiscValueB_2 EffectMiscValueB_3
EffectTriggerSpell_1 EffectTriggerSpell_2 EffectTriggerSpell_3 EffectPointsPerCombo_1
EffectPointsPerCombo_2 EffectPointsPerCombo_3 EffectSpellClassMaskA_1 EffectSpellClassMaskA_2
EffectSpellClassMaskA_3 EffectSpellClassMaskB_1 EffectSpellClassMaskB_2 EffectSpellClassMaskB_3
EffectSpellClassMaskC_1 EffectSpellClassMaskC_2 EffectSpellClassMaskC_3 SpellVisualID_1
SpellVisualID_2 SpellIconID ActiveIconID SpellPriority Name_Lang_enUS Name_Lang_enGB
Name_Lang_koKR Name_Lang_frFR Name_Lang_deDE Name_Lang_enCN Name_Lang_zhCN Name_Lang_enTW
Name_Lang_zhTW Name_Lang_esES Name_Lang_esMX Name_Lang_ruRU Name_Lang_ptPT Name_Lang_ptBR
Name_Lang_itIT Name_Lang_Unk Name_Lang_Mask NameSubtext_Lang_enUS NameSubtext_Lang_enGB
NameSubtext_Lang_koKR NameSubtext_Lang_frFR NameSubtext_Lang_deDE NameSubtext_Lang_enCN
NameSubtext_Lang_zhCN NameSubtext_Lang_enTW NameSubtext_Lang_zhTW NameSubtext_Lang_esES
NameSubtext_Lang_esMX NameSubtext_Lang_ruRU NameSubtext_Lang_ptPT NameSubtext_Lang_ptBR
NameSubtext_Lang_itIT NameSubtext_Lang_Unk NameSubtext_Lang_Mask Description_Lang_enUS
Description_Lang_enGB Description_Lang_koKR Description_Lang_frFR Description_Lang_deDE
Description_Lang_enCN Description_Lang_zhCN Description_Lang_enTW Description_Lang_zhTW
Description_Lang_esES Description_Lang_esMX Description_Lang_ruRU Description_Lang_ptPT
Description_Lang_ptBR Description_Lang_itIT Description_Lang_Unk Description_Lang_Mask
AuraDescription_Lang_enUS AuraDescription_Lang_enGB AuraDescription_Lang_koKR
AuraDescription_Lang_frFR AuraDescription_Lang_deDE AuraDescription_Lang_enCN
AuraDescription_Lang_zhCN AuraDescription_Lang_enTW AuraDescription_Lang_zhTW
AuraDescription_Lang_esES AuraDescription_Lang_esMX AuraDescription_Lang_ruRU
AuraDescription_Lang_ptPT AuraDescription_Lang_ptBR AuraDescription_Lang_itIT
AuraDescription_Lang_Unk AuraDescription_Lang_Mask ManaCostPct StartRecoveryCategory
StartRecoveryTime MaxTargetLevel SpellClassSet SpellClassMask_1 SpellClassMask_2
SpellClassMask_3 MaxTargets DefenseType PreventionType StanceBarOrder EffectChainAmplitude_1
EffectChainAmplitude_2 EffectChainAmplitude_3 MinFactionID MinReputation RequiredAuraVision
RequiredTotemCategoryID_1 RequiredTotemCategoryID_2 RequiredAreasID SchoolMask RuneCostID
SpellMissileID PowerDisplayID EffectBonusMultiplier_1 EffectBonusMultiplier_2
EffectBonusMultiplier_3 SpellDescriptionVariableID SpellDifficultyID
""".split()
# signed: 37
SPELL_DBC_SIGNED = """
ID unk_320_2 unk_320_3 PowerType Reagent_1 Reagent_2 Reagent_3 Reagent_4 Reagent_5 Reagent_6
Reagent_7 Reagent_8 ReagentCount_1 ReagentCount_2 ReagentCount_3 ReagentCount_4 ReagentCount_5
ReagentCount_6 ReagentCount_7 ReagentCount_8 EquippedItemClass EquippedItemSubclass
EquippedItemInvTypes EffectDieSides_1 EffectDieSides_2 EffectDieSides_3 EffectBasePoints_1
EffectBasePoints_2 EffectBasePoints_3 EffectMiscValue_1 EffectMiscValue_2 EffectMiscValue_3
EffectMiscValueB_1 EffectMiscValueB_2 EffectMiscValueB_3 RequiredAreasID PowerDisplayID
""".split()

# ---- skilllineability_dbc : 14 columns
SKILLLINEABILITY_DBC_COLUMNS = """
ID SkillLine Spell RaceMask ClassMask ExcludeRace ExcludeClass MinSkillLineRank
SupercededBySpell AcquireMethod TrivialSkillLineRankHigh TrivialSkillLineRankLow
CharacterPoints_1 CharacterPoints_2
""".split()
# signed: 14
SKILLLINEABILITY_DBC_SIGNED = """
ID SkillLine Spell RaceMask ClassMask ExcludeRace ExcludeClass MinSkillLineRank
SupercededBySpell AcquireMethod TrivialSkillLineRankHigh TrivialSkillLineRankLow
CharacterPoints_1 CharacterPoints_2
""".split()

# ---- charstartoutfit_dbc : 77 columns
CHARSTARTOUTFIT_DBC_COLUMNS = """
ID RaceID ClassID SexID OutfitID ItemID_1 ItemID_2 ItemID_3 ItemID_4 ItemID_5 ItemID_6 ItemID_7
ItemID_8 ItemID_9 ItemID_10 ItemID_11 ItemID_12 ItemID_13 ItemID_14 ItemID_15 ItemID_16
ItemID_17 ItemID_18 ItemID_19 ItemID_20 ItemID_21 ItemID_22 ItemID_23 ItemID_24 DisplayItemID_1
DisplayItemID_2 DisplayItemID_3 DisplayItemID_4 DisplayItemID_5 DisplayItemID_6 DisplayItemID_7
DisplayItemID_8 DisplayItemID_9 DisplayItemID_10 DisplayItemID_11 DisplayItemID_12
DisplayItemID_13 DisplayItemID_14 DisplayItemID_15 DisplayItemID_16 DisplayItemID_17
DisplayItemID_18 DisplayItemID_19 DisplayItemID_20 DisplayItemID_21 DisplayItemID_22
DisplayItemID_23 DisplayItemID_24 InventoryType_1 InventoryType_2 InventoryType_3
InventoryType_4 InventoryType_5 InventoryType_6 InventoryType_7 InventoryType_8 InventoryType_9
InventoryType_10 InventoryType_11 InventoryType_12 InventoryType_13 InventoryType_14
InventoryType_15 InventoryType_16 InventoryType_17 InventoryType_18 InventoryType_19
InventoryType_20 InventoryType_21 InventoryType_22 InventoryType_23 InventoryType_24
""".split()
# signed: 73
CHARSTARTOUTFIT_DBC_SIGNED = """
ID ItemID_1 ItemID_2 ItemID_3 ItemID_4 ItemID_5 ItemID_6 ItemID_7 ItemID_8 ItemID_9 ItemID_10
ItemID_11 ItemID_12 ItemID_13 ItemID_14 ItemID_15 ItemID_16 ItemID_17 ItemID_18 ItemID_19
ItemID_20 ItemID_21 ItemID_22 ItemID_23 ItemID_24 DisplayItemID_1 DisplayItemID_2
DisplayItemID_3 DisplayItemID_4 DisplayItemID_5 DisplayItemID_6 DisplayItemID_7 DisplayItemID_8
DisplayItemID_9 DisplayItemID_10 DisplayItemID_11 DisplayItemID_12 DisplayItemID_13
DisplayItemID_14 DisplayItemID_15 DisplayItemID_16 DisplayItemID_17 DisplayItemID_18
DisplayItemID_19 DisplayItemID_20 DisplayItemID_21 DisplayItemID_22 DisplayItemID_23
DisplayItemID_24 InventoryType_1 InventoryType_2 InventoryType_3 InventoryType_4 InventoryType_5
InventoryType_6 InventoryType_7 InventoryType_8 InventoryType_9 InventoryType_10
InventoryType_11 InventoryType_12 InventoryType_13 InventoryType_14 InventoryType_15
InventoryType_16 InventoryType_17 InventoryType_18 InventoryType_19 InventoryType_20
InventoryType_21 InventoryType_22 InventoryType_23 InventoryType_24
""".split()


# =============================================================================================
# The tables a NEW PLAYABLE CLASS needs, on top of the three above.
#
# Every one of these has a world-DB override table (DBCStores.cpp:284-400 passes a table name
# alongside every single LOAD_DBC), so the entire server half of a new class is SQL and
# /srv/wow/data/dbc stays byte-identical to stock -- the same property the Death Knight feature
# has. Format strings are copied VERBATIM from the pinned core's DBCfmt.h; column names and
# signedness come from `information_schema` on the live realm. Both are re-asserted at emit
# time, so a core bump that reshapes one of these fails the generator instead of the boot.
# =============================================================================================

# ---- chrclasses_dbc : 60 columns (DBCfmt.h:35)
# Where the class's NAME lives. Not GlobalStrings.lua: `FillLocalizedClassList` is a C function
# that reads this file, so "Demon Hunter" on the character sheet, in the create-screen class
# list and in `UnitClass()` all come from column 4 for free. Column 55 `Filename` is the class
# TOKEN ("WARRIOR", "DEATHKNIGHT") that FrameXML and GlueXML key CLASS_ICON_TCOORDS and
# RAID_CLASS_COLORS on, and column 59 `Required_Expansion` is checked against the account's
# expansion at CharacterHandler.cpp:315 -> CHAR_CREATE_EXPANSION_CLASS.
CHRCLASSES_FMT = "nxixssssssssssssssssxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxixii"
CHRCLASSES_DBC_COLUMNS = (
    ["ID", "Field01", "DisplayPower", "PetNameToken"]
    + [f"Name_Lang_{loc}" for loc in
       ("enUS enGB koKR frFR deDE enCN zhCN enTW zhTW esES esMX ruRU ptPT ptBR itIT Unk "
        "Mask").split()]
    + [f"Name_Female_Lang_{loc}" for loc in
       ("enUS enGB koKR frFR deDE enCN zhCN enTW zhTW esES esMX ruRU ptPT ptBR itIT Unk "
        "Mask").split()]
    + [f"Name_Male_Lang_{loc}" for loc in
       ("enUS enGB koKR frFR deDE enCN zhCN enTW zhTW esES esMX ruRU ptPT ptBR itIT Unk "
        "Mask").split()]
    + ["Filename", "SpellClassSet", "Flags", "CinematicSequenceID", "Required_Expansion"])
CHRCLASSES_DBC_SIGNED = """
ID Field01 DisplayPower PetNameToken SpellClassSet Flags CinematicSequenceID Required_Expansion
""".split()

# ---- skillline_dbc : 56 columns (DBCfmt.h:101)
# CategoryID 7 is SKILL_CATEGORY_CLASS; a class skill line here is what gives the spellbook a
# named tab. Stock IDs run 6..788.
SKILLLINE_FMT = "nixssssssssssssssssxxxxxxxxxxxxxxxxxxixxxxxxxxxxxxxxxxxi"
_LOCS = ("enUS enGB koKR frFR deDE enCN zhCN enTW zhTW esES esMX ruRU ptPT ptBR itIT Unk "
         "Mask").split()
SKILLLINE_DBC_COLUMNS = (
    ["ID", "CategoryID", "SkillCostsID"]
    + [f"DisplayName_Lang_{loc}" for loc in _LOCS]
    + [f"Description_Lang_{loc}" for loc in _LOCS]
    + ["SpellIconID"]
    + [f"AlternateVerb_Lang_{loc}" for loc in _LOCS]
    + ["CanLink"])
SKILLLINE_DBC_SIGNED = "ID CategoryID SkillCostsID SpellIconID CanLink".split()

# ---- skillraceclassinfo_dbc : 8 columns (DBCfmt.h:103)
# Binds a skill line to a race/class mask. Without a row here a class skill exists but nobody
# is eligible for it.
SKILLRACECLASSINFO_FMT = "diiiixix"
SKILLRACECLASSINFO_DBC_COLUMNS = """
ID SkillID RaceMask ClassMask Flags MinLevel SkillTierID SkillCostIndex
""".split()
SKILLRACECLASSINFO_DBC_SIGNED = SKILLRACECLASSINFO_DBC_COLUMNS

# ---- talenttab_dbc : 24 columns (DBCfmt.h:122)
# THE TRAP: DBCStores.cpp:554 skips any row whose `ClassMask & CLASSMASK_ALL_PLAYABLE` is zero,
# with the comment "prevent memory corruption; otherwise cls will become 12 below". Class 10's
# bit is not in that macro on stock, so a Demon Hunter talent tab is silently dropped and the
# class gets no talent panel at all. That single line is most of why the core patch exists.
TALENTTAB_FMT = "nxxxxxxxxxxxxxxxxxxxiiix"
TALENTTAB_DBC_COLUMNS = (
    ["ID"] + [f"Name_Lang_{loc}" for loc in _LOCS]
    + ["SpellIconID", "RaceMask", "ClassMask", "PetTalentMask", "OrderIndex", "BackgroundFile"])
TALENTTAB_DBC_SIGNED = "ID SpellIconID RaceMask ClassMask PetTalentMask OrderIndex".split()

# ---- talent_dbc : 23 columns (DBCfmt.h:121)
# One row per talent. SpellRank_1..5 are the spell ids of ranks 1..5; 6..9 exist in the file but
# the core marks them FT_NA and never reads them.
TALENT_FMT = "niiiiiiiixxxxixxixxixxx"
TALENT_DBC_COLUMNS = """
ID TabID TierID ColumnIndex SpellRank_1 SpellRank_2 SpellRank_3 SpellRank_4 SpellRank_5
SpellRank_6 SpellRank_7 SpellRank_8 SpellRank_9 PrereqTalent_1 PrereqTalent_2 PrereqTalent_3
PrereqRank_1 PrereqRank_2 PrereqRank_3 Flags RequiredSpellID CategoryMask_1 CategoryMask_2
""".split()
TALENT_DBC_SIGNED = TALENT_DBC_COLUMNS

# ---- spellshapeshiftform_dbc : 35 columns (DBCfmt.h:117)
# Row 22 is stock Metamorphosis (flags 0xd8, CreatureDisplayID_1 25277 = DemonForm.mdx). Rows
# 23 and 24 are entirely blank in the stock file -- two free form slots. Demon Hunter takes 23
# rather than reusing 22, so the warlock's form-22 passives cannot ride along.
SPELLSHAPESHIFTFORM_FMT = "nxxxxxxxxxxxxxxxxxxiixiiixxiiiiiiii"
SPELLSHAPESHIFTFORM_DBC_COLUMNS = (
    ["ID", "BonusActionBar"] + [f"Name_Lang_{loc}" for loc in _LOCS]
    + ["Flags", "CreatureType", "AttackIconID", "CombatRoundTime"]
    + [f"CreatureDisplayID_{i}" for i in range(1, 5)]
    + [f"PresetSpellID_{i}" for i in range(1, 9)])
SPELLSHAPESHIFTFORM_DBC_SIGNED = (
    ["ID", "BonusActionBar", "Flags", "CreatureType", "AttackIconID", "CombatRoundTime"]
    + [f"CreatureDisplayID_{i}" for i in range(1, 5)]
    + [f"PresetSpellID_{i}" for i in range(1, 9)])

# ---- CharBaseInfo.dbc : CLIENT ONLY, no SQL half
# 62 records of two bytes, `uint8 RaceID; uint8 ClassID;`, no index column and a one-byte string
# block. This is the race/class matrix the create screen greys buttons out from. There is no
# `CharBaseInfofmt` in DBCfmt.h and no reference to it anywhere in src/ -- the server's
# equivalent gate is which `playercreateinfo` rows exist, which is why elves-only needs BOTH
# halves and neither alone is sufficient.
CHARBASEINFO_FMT = "bb"
CHARBASEINFO_COLUMNS = ["RaceID", "ClassID"]


SPELL_DBC = DbcTable("spell_dbc", "Spell.dbc",
                     SPELL_ENTRY_FMT, SPELL_DBC_COLUMNS, SPELL_DBC_SIGNED)
SKILLLINEABILITY_DBC = DbcTable("skilllineability_dbc", "SkillLineAbility.dbc",
                                SKILL_LINE_ABILITY_FMT,
                                SKILLLINEABILITY_DBC_COLUMNS, SKILLLINEABILITY_DBC_SIGNED)
CHARSTARTOUTFIT_DBC = DbcTable("charstartoutfit_dbc", "CharStartOutfit.dbc",
                               CHAR_START_OUTFIT_FMT,
                               CHARSTARTOUTFIT_DBC_COLUMNS, CHARSTARTOUTFIT_DBC_SIGNED)
CHRCLASSES_DBC = DbcTable("chrclasses_dbc", "ChrClasses.dbc",
                          CHRCLASSES_FMT, CHRCLASSES_DBC_COLUMNS, CHRCLASSES_DBC_SIGNED,
                          # Filename ONLY. PetNameToken is an FT_NA string offset in the FILE
                          # but the world-DB column is `int` -- verified against
                          # information_schema: chrclasses_dbc.Filename is varchar(100),
                          # chrclasses_dbc.PetNameToken is int. Calling it a string here made
                          # the generator write 'PET' into an integer column, which MySQL
                          # rejects with "Incorrect integer value". A cloned row already
                          # carries a valid offset for it, so it never needs writing.
                          strings=("Filename",))
SKILLLINE_DBC = DbcTable("skillline_dbc", "SkillLine.dbc",
                         SKILLLINE_FMT, SKILLLINE_DBC_COLUMNS, SKILLLINE_DBC_SIGNED)
SKILLRACECLASSINFO_DBC = DbcTable("skillraceclassinfo_dbc", "SkillRaceClassInfo.dbc",
                                  SKILLRACECLASSINFO_FMT, SKILLRACECLASSINFO_DBC_COLUMNS,
                                  SKILLRACECLASSINFO_DBC_SIGNED)
TALENTTAB_DBC = DbcTable("talenttab_dbc", "TalentTab.dbc",
                         TALENTTAB_FMT, TALENTTAB_DBC_COLUMNS, TALENTTAB_DBC_SIGNED,
                         strings=("BackgroundFile",))
TALENT_DBC = DbcTable("talent_dbc", "Talent.dbc",
                      TALENT_FMT, TALENT_DBC_COLUMNS, TALENT_DBC_SIGNED)
SPELLSHAPESHIFTFORM_DBC = DbcTable("spellshapeshiftform_dbc", "SpellShapeshiftForm.dbc",
                                   SPELLSHAPESHIFTFORM_FMT, SPELLSHAPESHIFTFORM_DBC_COLUMNS,
                                   SPELLSHAPESHIFTFORM_DBC_SIGNED)
CHARBASEINFO_DBC = DbcTable(None, "CharBaseInfo.dbc",
                            CHARBASEINFO_FMT, CHARBASEINFO_COLUMNS, ())

# The REGISTRY -- every table this toolkit can read, not the set any one feature emits. A
# generator iterates its own spec's table tuple (dk_spec.DBC_TABLES, dh_spec.DBC_TABLES);
# iterating this one would try to save files it never opened.
ALL_TABLES = (SPELL_DBC, SKILLLINEABILITY_DBC, CHARSTARTOUTFIT_DBC, CHRCLASSES_DBC,
              SKILLLINE_DBC, SKILLRACECLASSINFO_DBC, TALENTTAB_DBC, TALENT_DBC,
              SPELLSHAPESHIFTFORM_DBC, CHARBASEINFO_DBC)
BY_SQL_NAME = {t.sql_table: t for t in ALL_TABLES if t.sql_table}
BY_DBC_FILE = {t.dbc_file: t for t in ALL_TABLES}


# =============================================================================================
# Gametables (gt*.dbc) are NOT DbcTables and cannot be.
#
# Their format string is "df" -- two SQL columns, ID and Data -- but the FILE has
# `field_count = 1, record_size = 4`: just the float. `d` is FT_SORT, which
# DBCFileLoader::GetFormatRecordSize (DBCFileLoader.cpp:146) adds ZERO bytes for, so the index
# is the row number and exists only on the SQL side. Every DbcTable invariant
# (`field_count == len(fmt)`, `record_size == format-implied size`) is therefore false for
# them, and forcing them through would mean weakening the assertions that protect the other
# nine tables.
#
# They matter because Blizzard filled the vacant class-10 slot with placeholders rather than
# zeroes -- 0.2 base melee crit, 1.0 HP regen ratio -- so a new class inherits nonsense unless
# each of these blocks is overwritten. Layout is (class - 1) * GT_MAX_LEVEL + (level - 1), i.e.
# class 10 owns rows 900..999 in the 1100-row files, and row 9 in the 11-row *Base files.
# =============================================================================================

GT_MAX_LEVEL = 100


class Gametable:
    """One gt*.dbc: a flat array of float32, indexed by row number."""

    def __init__(self, sql_table, dbc_file, per_class, comment):
        self.sql_table = sql_table
        self.dbc_file = dbc_file
        self.per_class = per_class      # rows per class: GT_MAX_LEVEL, or 1 for the *Base files
        self.comment = comment

    def block(self, class_id):
        """[lo, hi] inclusive row range this class owns."""
        lo = (class_id - 1) * self.per_class
        return lo, lo + self.per_class - 1


CLASS_GAMETABLES = (
    Gametable("gtchancetomeleecrit_dbc", "gtChanceToMeleeCrit.dbc", GT_MAX_LEVEL,
              "melee crit per point of agility"),
    Gametable("gtchancetomeleecritbase_dbc", "gtChanceToMeleeCritBase.dbc", 1,
              "flat base melee crit -- the stock class-10 value is 0.2, i.e. 20%"),
    Gametable("gtchancetospellcrit_dbc", "gtChanceToSpellCrit.dbc", GT_MAX_LEVEL,
              "spell crit per point of intellect"),
    Gametable("gtchancetospellcritbase_dbc", "gtChanceToSpellCritBase.dbc", 1,
              "flat base spell crit -- stock class-10 value is 0.2"),
    Gametable("gtoctregenhp_dbc", "gtOCTRegenHP.dbc", GT_MAX_LEVEL,
              "out-of-combat health regen base ratio"),
    Gametable("gtregenhpperspt_dbc", "gtRegenHPPerSpt.dbc", GT_MAX_LEVEL,
              "health regen per point of spirit"),
    Gametable("gtregenmpperspt_dbc", "gtRegenMPPerSpt.dbc", GT_MAX_LEVEL,
              "mana regen per point of spirit -- zero for every non-caster, including us"),
)

# gtOCTClassCombatRatingScalar is (class - 1) * GT_MAX_RATING + rating + 1, NOT per level, so it
# is listed apart from the block-copyable ones above. 32 ratings x 11 classes = 352 rows.
GT_MAX_RATING = 32
GT_CLASS_COMBAT_RATING_SCALAR = Gametable(
    "gtoctclasscombatratingscalar_dbc", "gtOCTClassCombatRatingScalar.dbc", GT_MAX_RATING,
    "per-class combat-rating scalars, indexed by rating rather than by level")
