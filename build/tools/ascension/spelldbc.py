"""Field offsets for a stock-layout 3.3.5a Spell.dbc (234 fields).

Ascension's Spell.dbc is 234 fields and record_size 936 = 234*4, i.e. it kept
Blizzard's layout and only added records -- verified before relying on it. That is
what makes importing from it possible at all: every balance cell we care about is
at the offset the WotLK core already expects, so a record can be copied across
without translation.
"""

ID                      = 0
CATEGORY                = 1
DISPEL                  = 2
MECHANIC                = 3
ATTRIBUTES              = 4      # .. 11 are AttributesEx1..7
SHAPESHIFT_MASK         = 12
TARGETS                 = 16
CASTING_TIME_INDEX      = 28
RECOVERY_TIME           = 29
CATEGORY_RECOVERY_TIME  = 30
INTERRUPT_FLAGS         = 31
AURA_INTERRUPT_FLAGS    = 32
PROC_TYPE_MASK          = 34
PROC_CHANCE             = 35
PROC_CHARGES            = 36
MAX_LEVEL               = 37
BASE_LEVEL              = 38
SPELL_LEVEL             = 39
DURATION_INDEX          = 40
POWER_TYPE              = 41
MANA_COST               = 42
RANGE_INDEX             = 46
SPEED                   = 47
EQUIPPED_ITEM_CLASS     = 68
EFFECT                  = 71     # +0/+1/+2
EFFECT_DIE_SIDES        = 74
EFFECT_PER_LEVEL        = 77
EFFECT_BASE_POINTS      = 80
EFFECT_MECHANIC         = 83
EFFECT_TARGET_A         = 86
EFFECT_TARGET_B         = 89
EFFECT_RADIUS_INDEX     = 92
EFFECT_AURA             = 95
EFFECT_AURA_PERIOD      = 98
EFFECT_AMPLITUDE        = 101
EFFECT_CHAIN_TARGETS    = 104
EFFECT_ITEM_TYPE        = 107
EFFECT_MISC_VALUE       = 110
EFFECT_MISC_VALUE_B     = 113
EFFECT_TRIGGER_SPELL    = 116
EFFECT_POINTS_PER_COMBO = 119
EFFECT_CLASS_MASK_A     = 122
SPELL_ICON_ID           = 133
NAME                    = 136    # Name_Lang_enUS
RANK                    = 153    # NameSubtext_Lang_enUS
DESCRIPTION             = 170
AURA_DESCRIPTION        = 187
MANA_COST_PCT           = 204
START_RECOVERY_CATEGORY = 205
START_RECOVERY_TIME     = 206
SPELL_CLASS_SET         = 208
SPELL_CLASS_MASK        = 209
SCHOOL_MASK             = 225
EFFECT_BONUS_MULTIPLIER = 229

FIELD_COUNT   = 234
RECORD_SIZE   = FIELD_COUNT * 4

# The names a human reads in the import report. Effect ids are the WotLK enum; anything
# not listed is either unused in the imported kit or genuinely not in this core.
EFFECT_NAMES = {
    0: "NONE", 1: "INSTAKILL", 2: "SCHOOL_DAMAGE", 3: "DUMMY", 6: "APPLY_AURA",
    8: "POWER_DRAIN", 9: "HEALTH_LEECH", 10: "HEAL", 15: "RESURRECT",
    16: "ADD_EXTRA_ATTACKS", 17: "DODGE", 18: "EVADE", 21: "OPEN_LOCK",
    24: "CREATE_ITEM", 26: "SUMMON", 27: "LEAP", 28: "ENERGIZE",
    30: "ENERGIZE", 31: "WEAPON_PERCENT_DAMAGE", 32: "TRIGGER_MISSILE",
    36: "LEARN_SPELL", 38: "DISPEL", 41: "JUMP", 42: "JUMP_DEST",
    44: "SKILL_STEP", 47: "TRADE_SKILL", 48: "STEALTH", 50: "TRANS_DOOR",
    53: "ENCHANT_ITEM", 58: "SUMMON_PET", 61: "WEAPON_DAMAGE_NOSCHOOL",
    62: "POWER_BURN", 64: "TRIGGER_SPELL", 65: "APPLY_AREA_AURA_PARTY",
    77: "SCRIPT_EFFECT", 78: "ATTACK", 84: "DISPEL_MECHANIC",
    88: "DURABILITY_DAMAGE", 96: "WEAPON_DAMAGE", 101: "FEED_PET",
    108: "DISPEL_MECHANIC", 113: "RESURRECT_NEW", 119: "APPLY_AREA_AURA_PET",
    121: "WEAPON_DAMAGE_NOSCHOOL", 122: "SUMMON_OBJECT_SLOT1",
    134: "KILL_CREDIT", 136: "HEAL_MECHANICAL", 137: "HEAL_PCT",
    138: "ENERGIZE_PCT", 145: "KNOCK_BACK_DEST", 149: "CHARGE_DEST",
    151: "TRIGGER_SPELL_2", 154: "TITAN_GRIP", 155: "ENCHANT_ITEM_PRISMATIC",
}
