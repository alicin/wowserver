/*
 * mod-demon-hunter -- module entry point.
 *
 * The function name is NOT free-form. modules/CMakeLists.txt ConfigureScriptLoader takes the
 * DIRECTORY name, replaces `-` with `_`, and generates a forward declaration plus a call to
 * `Add${that}Scripts()` into ModulesLoader.cpp:
 *
 *     mod-demon-hunter  ->  mod_demon_hunter  ->  Addmod_demon_hunterScripts()
 *
 * A mismatch is a link error at the very end of a 30-minute build, so it is worth reading twice.
 * Renaming build/modules/mod-demon-hunter/ means renaming this function too.
 *
 * Deliberately does not #include demon_hunter.h: a forward declaration is all this translation
 * unit needs, and it is what every installed module does (mod-learn-spells/src/LS_loader.cpp,
 * mod-dk-lowlevel/src/dk_lowlevel_loader.cpp).
 */

void AddSC_demon_hunter();

void Addmod_demon_hunterScripts()
{
    AddSC_demon_hunter();
}
