/*
 * mod-utility-npcs -- module entry point.
 *
 * The function name is NOT free-form. modules/CMakeLists.txt ConfigureScriptLoader takes the
 * DIRECTORY name, replaces `-` with `_`, and generates a forward declaration and a call to
 * `Add${that}Scripts()` into ModulesLoader.cpp:
 *
 *     mod-utility-npcs  ->  mod_utility_npcs  ->  Addmod_utility_npcsScripts()
 *
 * A mismatch is a link error at the very end of a 30-minute build, so it is worth reading twice.
 * Renaming build/modules/mod-utility-npcs/ means renaming this function too.
 *
 * Deliberately does not #include utility_npcs.h: a forward declaration is all this translation
 * unit needs, and it is what every installed module does (mod-dk-lowlevel/src/dk_lowlevel_loader.cpp,
 * mod-learn-spells/src/LS_loader.cpp, mod-instance-reset/src/mir_loader.cpp).
 */

void AddSC_utility_npcs();

void AddSC_npc_talent_master();
void Addmod_utility_npcsScripts()
{
    AddSC_npc_talent_master();
    AddSC_utility_npcs();
}
