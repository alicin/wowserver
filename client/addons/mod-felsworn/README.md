# The Felsworn client addon

Double jump and glide, plus the three FrameXML tables an eleventh class breaks.

This file is the argument. The code is commented, but the reasoning that decides the *shape* of
the code is long enough that it belongs here: what a 3.3.5a client will and will not let an
addon do about a keypress, how that was established, and which part of the brief cannot be
built as written and what was built instead.

Everything asserted below was read out of a file on this machine. Where a claim is not
verified it says so.

**Sources used, all read directly:**

| what | where |
|---|---|
| The client's FrameXML | extracted from `<client>/Data/enUS/patch-enUS{,-2,-3}.MPQ` with `build/tools/acdbc/mpqlib.py`. Paths below are the archive paths, e.g. `Interface\FrameXML\RestrictedFrames.lua`. |
| `Wow.exe` | `/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Wow.exe`, addresses are VAs at image base 0x400000 |
| `ChrClasses.dbc` | `/srv/wow/data/dbc/ChrClasses.dbc`, read with `build/tools/acdbc` |
| house precedent | `client/addons/mod-item-browser/ItemBrowser/`, `docs/death-knights.md`, `build/patches/README.md`, `client/tools/patch-wow-exe.py` |

---

## 1. What ships

```
.work/dh-parts/addon/
  Felsworn/                <- the AddOns folder, installed verbatim as AddOns/Felsworn
    Felsworn.toc
    Core.lua                  namespace, saved variable, event frame, class gate, /dh
    ClassUI.lua               CLASS_ICON_TCOORDS / RAID_CLASS_COLORS / LOCALIZED_CLASS_NAMES
    Movement.lua              the secure buttons, the bindings, the airborne poll
    Bindings.xml              the two keybinds (loaded by the client, never from the .toc)
  tools/
    selftest.lua              29 checks under stub widgets; `luajit tools/selftest.lua`
  NOTES.md                    this file
```

Declared in `client/addons.txt` exactly the way ItemBrowser is (that file's header, lines 8-11):

```
# repo                                         ref      mode              sha
client/addons/mod-demon-hunter/Felsworn     -        local:Felsworn -
```

`local:Felsworn` and not `local:demonhunter`: the folder name is what the client uses for
`Interface\AddOns\<name>\Bindings.xml`, and the `.toc` basename must match the folder.

When it is integrated, `Felsworn/` moves to `client/addons/mod-demon-hunter/Felsworn/`
and `tools/` beside it, mirroring `client/addons/mod-item-browser/`; the `addons.txt` line above
already points there.

**The spell ids are placeholders.** `Movement.lua` lines 101-102:

```lua
local DH_SPELL_DOUBLE_JUMP = 91000      -- PLACEHOLDER
local DH_SPELL_GLIDE       = 91001      -- PLACEHOLDER
```

Two consecutive lines at the top of the file, marked, so the generator can rewrite them
mechanically. They sit inside the band `docs/death-knights.md` §1.3 establishes for custom
spells — above `Spell.dbc`'s real maximum of 80864, below AzerothCore's own server-side band
starting at 100001 — and outside 90000–90119, which that document already reserves for the
Death Knight ability blocks. They are provisional values, not proposals: nothing has been
generated yet, and `/dh status` prints, per ability, whether the id resolves in the client's
own `Spell.dbc`, so a forgotten placeholder announces itself.

---

## 2. Double jump: what is actually possible

The brief's constraints were re-derived rather than taken on trust, because the whole design
turns on them.

### 2.1 Raw key sniffing is out

`SetPropagateKeyboardInput` does not exist in this build. Searched as a NUL-delimited symbol in
`Wow.exe`: **0 occurrences**. The controls it would be sitting next to are all there —

| symbol | .rdata offset |
|---|---|
| `CastSpellByID` | 0x609408 |
| `ClearOverrideBindings` | 0x60d418 |
| `GetBindingKey` | 0x60d408 |
| `InCombatLockdown` | 0x5fbc88 |
| `IsFalling` | 0x61d678 |
| `JumpOrAscendStart` | 0x61c638 |
| `SetOverrideBindingClick` | 0x60d430 |
| `SetPropagateKeyboardInput` | **absent** |

A frame with `EnableKeyboard(true)` and no way to propagate swallows every key it is shown for,
including whatever the player has bound to chat. Not an option.

### 2.2 The cast has to come out of a secure button

The client's own `SECURE_ACTIONS.spell` (`Interface\FrameXML\SecureTemplates.lua`) is:

```lua
local spell = SecureButton_GetModifiedAttribute(self, "spell", button);
local spellID = tonumber(spell);
if ( spellID) then
    CastSpellByID(spellID, unit);
elseif ( spell ) then
    CastSpellByName(spell, unit);
end
```

Two useful facts fall out of that.

* **A number in the `spell` attribute reaches `CastSpellByID`.** So the addon never needs the
  spell's *name*, which matters more than usual here: `GetSpellInfo` on a custom id returns
  `nil` on a client without the realm's patch archive, and a name-based button would then bind
  to nothing at all, silently. An id-based button binds regardless, and the missing-archive
  case gets one explicit line at login instead — the same failure `docs/death-knights.md` §4.6
  describes for a level-1 Death Knight with no `patch-Z.MPQ`.
* That function is reached from `SecureActionButton_OnClick`, which the client invokes itself
  when a binding says CLICK. Reached from addon Lua instead, it is a protected call on a
  tainted stack and is refused. **This is why the two `<Binding>` bodies in `Bindings.xml` do
  not cast anything** — they cannot, so they are diagnostics instead (§2.7).

### 2.3 Why the binding is swapped and not the attribute

`SecureActionButtonTemplate` inherits `SecureFrameTemplate`, which is declared
`protected="true"` — `Interface\FrameXML\SecureTemplates.xml:4` and `:11`. Attributes of a
protected frame cannot be written by insecure code during combat lockdown.

The design the brief sketches — one permanently bound button whose `spell` attribute is set
while airborne and cleared while grounded — therefore has two problems, and the second is worse
than the first:

1. whatever the attribute says when combat starts is what it says for the rest of the fight;
2. **clearing `spell` does not restore the jump.** The override binding is still installed, so
   a grounded press clicks a button that does nothing at all. The player cannot jump. There is
   no "falls through to a normal jump" — an override binding replaces the underlying binding
   outright.

So `Movement.lua` swaps the **binding**, not the attribute:

* attributes are written exactly once, out of combat, and never touched again;
* the jump key is taken over only while `IsFalling()` is true, and released the instant it is
  false.

That inversion is the point. The state we want during combat (no override, jump key jumps) is
the *same* state we want while grounded, so freezing the grounded state is harmless. Only one
window is left over, and §2.6 accounts for it.

### 2.4 The secure-snippet route, and exactly where it dies

The brief asks whether a secure snippet reacting to a state driver can do the swap in combat.
It cannot, and it is worth writing down why, because the mechanism looks like it should.

**The half that works.** A snippet *can* rebind keys during combat.
`Interface\FrameXML\RestrictedFrames.lua:525-585` exposes exactly that into the restricted
environment:

```lua
function HANDLE:ClearBindings()
    ClearOverrideBindings(GetHandleFrame(self));
end
...
function HANDLE:SetBindingClick(priority, key, name, button)
    ...
    SetOverrideBindingClick(GetHandleFrame(self), priority, key, name, button);
end
```

Blizzard would not have needed those wrappers if the underlying calls were usable from ordinary
code in a fight. (That is also the strongest in-file evidence available here that
`SetOverrideBindingClick` is `#nocombat`; FrameXML itself never calls it, so there is no
comment to cite.) And `SecureHandlers.lua:327-329` shows a wrapped script still runs its
snippet in combat as long as the frame is protected:

```lua
local function IsWrapEligible(frame)
    return (not InCombatLockdown()) or frame:IsProtected();
end
```

So `SecureHandlerWrapScript(button, "PreClick", header, snippet)` genuinely does give a secure
execution on every keypress, in combat, that could rewrite the button's attributes before
`SecureActionButton_OnClick` reads them.

**The half that does not.** That snippet cannot find out that the player is airborne. Three
independent doors, all shut:

* **The restricted environment has no `IsFalling`.** `RestrictedEnvironment.lua:99-183` is the
  complete list of what a snippet may call. Lines 165-166 are
  `IsMounted, IsSwimming, IsFlying, IsFlyableArea, IsIndoors, IsOutdoors`. `IsFalling` is not
  in the file.
* **There is no `falling` macro conditional,** so `SecureCmdOptionParse` — which *is* in the
  restricted scope (`RestrictedEnvironment.lua:156`) and is what `RegisterStateDriver` evaluates
  (`SecureStateDriver.lua:89`, `:139`) — cannot express it either. The conditional keyword table
  in `Wow.exe` runs 0x00a1d24c–0x00a1d334 and is immediately followed by the source path
  `.\UIMacroOptions.cpp` at 0x00a1d33c, which is what identifies it. Read out in order it is

  ```
  unithasvehicleui vehicleui spec channeling worn equipped bonusbar bar actionbar
  btn button mod modifier form stance stealth mounted flying swimming outdoors
  indoors flyable dead harm help exists
  ```

  `flying` is a flying mount. There is no `falling`, `jumping` or `airborne` string anywhere in
  the binary.
* **Insecure code cannot hand the value in during a fight.** Writing it to the handler is
  blocked, because a handler frame must be *explicitly protected* to have a managed environment
  at all (`SecureHandlers.lua:73-77`), and reading it back off an unprotected frame fails
  inside the snippet — `RestrictedFrames.lua:142-155`:

  ```lua
  local function GetHandleFrame(handle)
      local frame = LOCAL_FrameHandle_Protected_Frames[handle];
      if (not frame) then
          frame = LOCAL_FrameHandle_Other_Frames[handle];
          if (frame) then
              if (frame:IsProtected() or not InCombatLockdown()) then
                  return frame;
              end
          end
          error("Invalid frame handle");
  ```

  Protected enough for the snippet to read means protected enough that we cannot write it.

For completeness, the outer door is shut too: `RestrictedExecution.lua:815-818` refuses to enter
a snippet from a tainted stack at all —

```lua
if (not issecure()) then
    error("Cannot call restricted closure from insecure code");
```

— so "just call `SetAttribute` and let `_onstate-x` fire" is not a route even out of combat when
the caller is tainted; the supported entries are the ones Blizzard drives from its own secure
code (`SecureStateDriverManager`'s `OnUpdate`, `SecureStateDriver.lua:81-114`, throttled to
0.2 s at `:54`) or from a real click.

**Conclusion.** The mechanism to rebind in combat exists; the fact needed to decide *what* to
rebind cannot cross into it. So the snippet route buys nothing over a plain
`SetOverrideBindingClick` made out of combat, and costs a restricted environment nobody can
debug at 3 a.m. It is not used. It was not skipped for effort.

### 2.5 What is actually shipped

Two ways to double jump, deliberately different in character:

**A dedicated "Double Jump" keybind — always works, in combat and out.** `Bindings.xml`
declares `FELSWORN_DOUBLE_JUMP`; the player binds whatever key they like under
Key Bindings → Felsworn. On `PLAYER_LOGIN` and on every `UPDATE_BINDINGS`, out of combat,
the addon mirrors that key onto the secure button with `SetOverrideBindingClick(permOwner,
true, key, "FelswornDoubleJumpButton", "LeftButton")`. It is installed once and never
changes, so lockdown never touches it. This is the reliable path, and it is the one to tell
players about.

**A jump-key overlay — a convenience, out of combat only.** A 20 Hz poll on `IsFalling()`
installs the same override on whatever `GetBindingKey("JUMP")` returns while the player is
airborne, and clears it when they land. Grounded, the override simply is not there, so the jump
key jumps — that is the brief's "falls through to a normal jump", achieved by not being in the
way rather than by being in the way and doing nothing. `/dh jumpkey off` disables it
permanently (the one saved variable; see `Core.lua`'s header for why it is saved and not
per-session).

Two separate owner frames, `FelswornBindingOwner` and `FelswornJumpOverlayOwner`, because
`ClearOverrideBindings` takes an owner and clears *everything* that owner installed. On one
owner, every landing would also wipe the player's Double Jump and Glide keys.

### 2.6 The one window that is knowingly wrong

If combat starts while the player is in the air, the overlay is installed and cannot be
removed, so the jump key casts Double Jump instead of jumping until the fight ends. There is no
client-side fix — that is what §2.4 proves. Three things narrow it:

* the exposure is only the airborne part of a jump, roughly a second, not the whole session;
* `PLAYER_REGEN_ENABLED` clears it as the first thing it does;
* `/dh jumpkey off` removes the behaviour entirely for anyone who would rather bind a key.

Scenario 3 in `tools/selftest.lua` reproduces exactly this sequence and asserts both halves: no
binding call is attempted during the fight, and the stale override is gone the moment it ends.

### 2.7 Small things that were checked rather than assumed

* **The buttons fire on key *down*.** `RegisterForClicks("AnyDown")`, matching the stock JUMP
  binding, which acts on `keystate == "down"` (`Interface\FrameXML\Bindings.xml:52-58`).
  `AnyUp` and `AnyDown` are adjacent strings in `Wow.exe` at 0x69f38f and 0x69f397, and
  FrameXML uses `RegisterForClicks("AnyUp")` at `AudioOptionsPanels.xml:969`, so both values
  are real in this build.
* **The buttons are shown, not hidden.** 1×1, no textures, bottom-left corner. The binding
  system reaches them by name through a CLICK action, and a shown button is the shape every
  click-cast addon on this client uses; a hidden one is a class of bug nobody wants to be
  debugging mid-fight.
* **The stock JUMP binding's key-*release* half does not run while the overlay is installed**
  (it calls `AscendStop()`). That is fine, because the overlay only exists while `IsFalling()`
  is true, and `IsFalling()` is false while swimming or on a flying mount — the only two states
  where there is an ascent to stop.
* **50 ms is the worst case for "I left the ground but the overlay is not up yet."** A human
  cannot press the jump key twice inside 50 ms; if they somehow do, the second press is an
  ordinary airborne jump, which the client ignores. Nothing misfires.
* **`/reload` mid-fight is handled.** `PLAYER_LOGIN` normally arrives on a loading screen where
  `InCombatLockdown()` is false — but not then. Everything is deferred to
  `PLAYER_REGEN_ENABLED` rather than firing four action-blocked errors into somebody's pull.
  Scenario 4 in the selftest covers it; it is what caught the one real bug found during
  development (`SyncOverlay` trusting a cached `airborne` that the stopped poller had not
  updated).

---

## 3. Glide

Mechanically identical: a second secure button, a second dedicated keybind, one permanent
override. There is no jump-key overlay for it.

**The `IsFalling()` gate the brief asks for cannot be applied in combat, and applying it only
out of combat would be worse than not applying it.** The reasoning is the mirror image of
§2.3. Ask what state the glide key should be in when combat starts:

* if the answer is "bound", the addon must never unbind it out of combat either, because
  combat can start between two polls — so no gate;
* if the answer is "unbound while grounded", then a player who enters combat standing on the
  ground has no Glide key for the whole fight, and Glide is a spell whose whole purpose is not
  dying to a fall.

The second is much worse than a wasted global cooldown. So the key stays bound, always, and
**the ground check belongs on the server**: a Glide cast by a caster who is not falling should
fail with `SPELL_FAILED_DONT_REPORT` and consume no GCD. That is a requirement this addon is
placing on the other half of the feature, not an oversight — see §5.

The same applies to a grounded Double Jump, which can happen through the dedicated key or
during the §2.6 window.

---

## 4. Class UI fix-ups, and why they are not class-gated

`ClassUI.lua` fills in `RAID_CLASS_COLORS.FELSWORN`, `CLASS_ICON_TCOORDS.FELSWORN` and
`LOCALIZED_CLASS_NAMES_{MALE,FEMALE}.FELSWORN`, each only if absent.

**It runs for every character, not just Felsworns.** The player who gets the nil-index
error is not the Felsworn — it is the priest who invites one, because party and raid frames
key on the class token of the *unit*. A class gate here would protect precisely the one person
who never needed protecting. Part D of the brief (be inert for non-Demon-Hunters) is
implemented against `Movement.lua`, which is where the cost is: `Core.lua` calls
`UnregisterAllEvents()` at `PLAYER_LOGIN` and no secure button, owner frame or `OnUpdate` is
ever created.

**The values.**

* Colour `A330C9` → `{ r = 0.64, g = 0.19, b = 0.79 }`. **Not read out of any file in this
  repo** — there is no 3.3.5a source for it, because the class does not exist in 3.3.5a. It is
  the value the class shipped with in retail, recorded so that the addon, the patched
  `Constants.lua` and any future generator agree on one number.
* T-coords `{0.5, 0.75, 0.5, 0.75}` — the next unused cell of the 4×4 grid in the client's
  `Constants.lua:91-102`. Row 3 there is `PALADIN {0, 0.25, 0.5, 0.75}` then
  `DEATHKNIGHT {0.25, .5, 0.5, .75}`; this is the cell immediately after them, untrimmed like
  both neighbours (rows 1 and 2 use trimmed edges such as `0.49609375` = 127/256; row 3 does
  not). **Whoever ships the class-icon atlas must put the Felsworn icon in that cell.**
  One decision, expressed in two places.
* Names "Felsworn", male and female. On a client whose `ChrClasses.dbc` carries the class
  10 record these are already correct — `Constants.lua:87-88` calls `FillLocalizedClassList`,
  which reads the DBC — so this branch is the missing-archive case again.

**Deliberately not touched: `CLASS_SORT_ORDER` and `MAX_CLASSES`.** `Constants.lua:83` computes
`MAX_CLASSES = #CLASS_SORT_ORDER` at load, and FrameXML files walk `CLASS_SORT_ORDER` while
loading, i.e. before any addon exists. Appending from an addon would leave the two disagreeing
for the rest of the session — strictly worse than the missing entry. That pair is the patched
`Constants.lua`'s job, and `client/tools/patch-wow-exe.py` (docstring, lines 60-65) says so as
the reason both signature checks are patched rather than only GlueXML's.

**The token must be spelled `FELSWORN`.** `select(2, UnitClass(unit))` returns
`ChrClasses.dbc` column `Filename`. Read off the stock server file
`/srv/wow/data/dbc/ChrClasses.dbc` — 10 records, IDs 1–9 and 11, ID 10 absent:

```
ID  DisplayPower  Name_Lang_enUS   Filename
 1       1        Warrior          WARRIOR
 4       3        Rogue            ROGUE
 6       6        Death Knight     DEATHKNIGHT
11       0        Druid            DRUID
```

(Rogue's `DisplayPower` 3 is ENERGY, which is the value the Felsworn row takes per the
project decisions.) If the generator writes any other `Filename`, this addon goes inert on a
real Felsworn and nothing says why — so `/dh status` prints the token it actually saw.

---

## 5. What this addon needs from the server half

Four things, none of which the client can supply:

1. **`ChrClasses.dbc` class 10 with `Filename = "FELSWORN"`.** §4.
2. **Real spell ids for `DH_SPELL_DOUBLE_JUMP` and `DH_SPELL_GLIDE`,** written into the two
   marked lines at the top of `Movement.lua`, present in *both* the client's `Spell.dbc` and
   `acore_world.spell_dbc` — the same two-halves-one-generator rule as
   `docs/death-knights.md` §3.
3. **Double Jump must be castable while airborne and must not require a target.** The button
   sets no `unit` attribute, so `SecureActionButton_OnClick` passes `unit = nil` through to
   `CastSpellByID`.
4. **A cast of either spell while the caster is not falling must fail silently and cost no
   global cooldown** (`SPELL_FAILED_DONT_REPORT`). §3 is the argument; the short version is
   that the client physically cannot make that decision during combat, so if the server does
   not make it, nobody does.

---

## 6. Verifying it

Out of game:

```bash
cd .work/dh-parts/addon
luajit tools/selftest.lua        # 29 checks, prints "selftest: PASS"
```

In game, on a Felsworn, once the ids are real:

1. `/dh status` — both abilities show a resolved spell name, not
   `(NOT IN THIS CLIENT'S Spell.dbc)`. If they do not, the client patch is missing; nothing
   below will work.
2. Bind a key to **Double Jump** under Key Bindings → Felsworn. `/dh status` shows it.
3. On flat ground, press the jump key. You jump normally — `/dh status` mid-air would show
   `overlay: ACTIVE`, on the ground `idle`.
4. Jump, then press the jump key again in mid-air. **Second jump.** This is the acceptance
   test for the overlay.
5. Jump, then press your dedicated Double Jump key in mid-air. Same result, different path.
6. Enter combat standing still. Press the jump key: you jump. Press the dedicated key in
   mid-air: **you double jump.** This is the acceptance test for the in-combat path, and it is
   the one that matters — see §2.6 for the case that does not work.
7. `/dh jumpkey off`, jump twice: only the first works, the dedicated key still does. Relog:
   still off.
8. Fall off something and press Glide. Feather-fall plus forward momentum, per the server half.
9. Log in a priest, invite the Felsworn to a party. No Lua errors, class-coloured row,
   correct icon. This is §4's whole reason for existing.
10. `/reload` while in combat on the Felsworn. No "action blocked" popup. When the fight
    ends, both keys work again with no further action.

---

## 7. Known limits

| limit | why | where |
|---|---|---|
| Combat that starts while airborne leaves the jump key pointed at Double Jump until it ends | no client-side way to change a binding under lockdown, and no way to tell a secure snippet the player is airborne | §2.4, §2.6 |
| A grounded cast of either spell is not suppressed by the client | same | §3, §5.4 |
| A key bound during combat does not take effect until combat ends | `SetOverrideBindingClick` is `#nocombat`; the binding body says so instead of doing nothing | `Bindings.xml`, `FelswornMovement_BindingPressed` |
| Holding the jump key in mid-air sends repeated casts | deliberate: the server's cooldown is the authority, and a client-side latch would be a second source of truth to get out of sync | `Movement.lua` |
| The two keybinds appear in the Key Bindings panel for every class | the client loads an addon's `Bindings.xml` regardless of who is logged in; hiding the labels would replace two readable rows with two raw binding names | `Core.lua`, bottom |
| The class colour is not sourced from a file | the class does not exist in 3.3.5a; there is nothing to read | §4 |
