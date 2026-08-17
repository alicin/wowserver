# Core patches

Patches applied to the pinned AzerothCore checkout during the image build, in filename order,
between the module clone loop and the compile (`build/Dockerfile`).

**This directory is a last resort and should stay nearly empty.** Everything this server does is
a module or a SQL row, for the reason `docs/modules.md` gives: a module survives a core bump,
and a patch has to be re-checked against every one. The bar for adding a file here is that the
thing being changed is *unreachable* from a script hook — not merely inconvenient.

The build applies each patch with `git apply --check` first, so a core bump that invalidates one
of these fails in CI, at the `git apply` step, with the offending file named. It does not fail
silently and it does not fail three-quarters of the way through a compile.

---

## 0001-demon-hunter-class-10.patch

Eight lines across three files. Makes class **10** — the vacant `//CLASS_UNK = 10` slot between
Warlock and Druid — a usable player class. See `docs/demon-hunters.md` §3.

Nothing here adds a feature. Every line fills in a hole that Blizzard's own data files already
have and that AzerothCore inherited: `ChrClasses.dbc` ships ten records with IDs 1–9 and 11, and
the core's per-class tables carry a matching `0.0f, // ??` placeholder at the missing index.

### `src/server/shared/SharedDefines.h` — 2 lines

```c
-    //CLASS_UNK           = 10,
+    CLASS_DEMON_HUNTER  = 10, // TITLE Demon Hunter
```

Naming the slot. `MAX_CLASSES` is already **12**, so no array is resized and no bound moves —
class 10 was always inside every `[MAX_CLASSES]` array and every `class_ >= MAX_CLASSES` guard.
(Class *12* would not be: it is the exact index that overflows. This is why the feature uses the
hole rather than appending.)

```c
-    (1<<(CLASS_DEATH_KNIGHT-1)))
+    (1<<(CLASS_DEATH_KNIGHT-1))|(1<<(CLASS_DEMON_HUNTER-1)))
```

`CLASSMASK_ALL_PLAYABLE` is a validity filter, not a convenience constant. Ten call sites drop
rows whose class mask is not inside it, all of them silently, with at most a log line:

| what would be dropped | site |
|---|---|
| **every Demon Hunter talent tab** | `DBCStores.cpp:554` |
| item `AllowableClass` | `ObjectMgr.cpp:3586` |
| `playercreateinfo_spell` / `_action` / `_item` class masks | `ObjectMgr.cpp:4548, 4615, 4673` |
| quest `RequiredClasses` | `ObjectMgr.cpp:5354` |
| `conditions` class mask | `ConditionMgr.cpp:2195` |
| achievement criteria race/class | `AchievementMgr.cpp:115, 275` |

The talent one decides it. `DBCStores.cpp:554` reads

```cpp
// prevent memory corruption; otherwise cls will become 12 below
if ((talentTabInfo->ClassMask & CLASSMASK_ALL_PLAYABLE) == 0)
    continue;
```

so without this line the three authored talent trees are read from the DBC, skipped, and the
class has an empty talent panel from level 10 to 80 with no error anywhere.

### `StatSystem.cpp` and `Player.cpp` — 6 float literals

Six per-class tables have a `0.0f, // ??` at index 9 (= class 10). They are indexed
`getClass() - 1` **directly**, not through `Player::IsClass`, so unlike the other 134 class
decision points in the core they cannot be intercepted by a module's `OnPlayerIsClass` hook.
That is the entire reason this patch exists rather than being part of `mod-demon-hunter`.

| file:line | array | stock | patched |
|---|---|---|---|
| `StatSystem.cpp:722` | `m_diminishing_k` | `0.0f` | `0.9880f` |
| `StatSystem.cpp:739` | `miss_cap` | `0.0f` | `16.00f` |
| `StatSystem.cpp:766` | `parry_cap` | `0.0f` | `145.560408f` |
| `StatSystem.cpp:812` | `dodge_cap` | `0.0f` | `145.560408f` |
| `Player.cpp:5290` | `dodge_base` | `0.0f` | `0.020957f` |
| `Player.cpp:5305` | `crit_to_dodge` | `0.0f` | `2.00f / 1.15f` |

Every value is copied from the **Rogue** column (index 3), which is what the class is modelled
on everywhere else: leather, agility-scaling, dual-wield, parries.

Leaving them at `0.0f` is not "no bonus", it is **NaN**. `Player::GetDodgeFromAgility`
(`Player.cpp:5325-5327`) computes

```cpp
diminishing    = 100.0f * bonus_agility * dodgeRatio->ratio * crit_to_dodge[pclass - 1];
nondiminishing = 100.0f * (dodge_base[pclass - 1] + base_agility * dodgeRatio->ratio * crit_to_dodge[pclass - 1]);
```

With `crit_to_dodge = 0` both come out 0 regardless of gear, and `StatSystem.cpp:827` then
evaluates

```cpp
m_realDodge = nondiminishing + (diminishing * dodge_cap[pclass] / (diminishing + dodge_cap[pclass] * m_diminishing_k[pclass]));
//            0              + (0           * 0                 / (0           + 0                * 0))   ->  0/0  ->  NaN
```

`m_realDodge` feeds the melee hit-outcome roll, and every comparison against NaN is false, so
the symptom is not a wrong dodge chance — it is a character that **never dodges or parries**,
for its entire life, while the character sheet displays a plausible number (the sheet uses
`value`, computed separately). `GetMissPercentageFromDefence` has the same 0/0 at
`StatSystem.cpp:749`.

### Verifying after a core bump

```bash
git -C .work/ac-src apply --check build/patches/0001-demon-hunter-class-10.patch
```

If that fails, do **not** rebase the hunks blindly. The six float tables are positional: confirm
the placeholder is still at index 9 and still reads `// ??`, because a core that filled the slot
in itself would make this patch a silent double-write of someone else's intended value.


---

## 0002-learn-spells-skip-demon-hunter.patch

One `case` label, in a **module**, not the core. `modules/mod-learn-spells/src/mod_learnspells.cpp`.

`mod-learn-spells` is pinned in `build/modules.txt` and enabled on this realm
(`LearnSpells.Enable = 1`). It teaches a character every spell of its class at every level, and
it decides "its class" like this:

```cpp
uint32 GetSpellFamily(const Player* p)
{
    switch (p->getClass())
    {
    case CLASS_ROGUE:  return SPELLFAMILY_ROGUE;
    ...
    default:           return SPELLFAMILY_GENERIC;      // <- class 10 lands here
    }
}
```

Class 10 is the first class in the game's history to reach that `default`, and the scan it feeds
has **no class check of any kind**:

```cpp
if (spellInfo->SpellFamilyName != family) continue;
...
if (itr->second->Spell == spellInfo->Id && itr->second->RaceMask == 0
    && itr->second->AcquireMethod == 0) valid = true;
```

`SPELLFAMILY_GENERIC` is family **0** — the family of every unclassed spell in the game. So a
Demon Hunter would be handed every family-0 spell whose `BaseLevel` matches the level it just
reached and which has one permissive SkillLineAbility row. Measured on this realm: **15 spells at
level 1** (Parry, four ranks of Intercept, Vampiric Touch, Flash of Light, Spirit Weapons…), 59
Enchanting recipes at 35, 38 Alchemy recipes at 45, 79 at level 60.

It is not gated by `DemonHunter.Enable`, there is no config knob that exempts a class, and no
module hook can reach it — `GetSpellFamily` is a private method of the module's own script class.

**Why 14 and not 16.** 16 is the Demon Hunter's own family. Returning it would make this module
grant the class's real spells at their `BaseLevel`, bypassing `mod-demon-hunter`'s progression
table entirely and handing out the off-hand mirrors and triggered second records that nobody is
ever meant to learn. Family **14** has zero members across all 49,839 records in `Spell.dbc`
— histogrammed, not assumed — so the scan matches nothing and the module correctly does nothing
for this class.

**The alternative was `LearnSpells.Enable = 0`**, which would take the feature away from the
other ten classes to fix one. This patch is nineteen lines including its comment.

### A note on patching a module rather than the core

`git apply` runs in `/src`, and the modules are cloned to `/src/modules/<name>` by the loop
above it, so a patch whose paths begin `modules/mod-learn-spells/` applies exactly like a core
one — verified against a reproduction of the image layout, not assumed. The module being a
separate git repo does not matter; `git apply` patches paths, not tracked objects.

The cost is the same as any pin: bumping `mod-learn-spells` in `build/modules.txt` may invalidate
this patch, and CI will say so at the `git apply --check` step.
