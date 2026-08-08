/*
 * mod-dk-lowlevel -- module entry point.
 *
 * The function name is NOT free-form. modules/CMakeLists.txt ConfigureScriptLoader (lines
 * 144-181) takes the DIRECTORY name, replaces `-` with `_`, and generates a forward declaration
 * and a call to `Add${that}Scripts()` into ModulesLoader.cpp:
 *
 *     mod-dk-lowlevel  ->  mod_dk_lowlevel  ->  Addmod_dk_lowlevelScripts()
 *
 * A mismatch is a link error at the very end of a 30-minute build, so it is worth reading twice.
 * Renaming build/modules/mod-dk-lowlevel/ means renaming this function too.
 *
 * Deliberately does not #include dk_lowlevel.h: a forward declaration is all this translation
 * unit needs, and it is what every installed module does (mod-learn-spells/src/LS_loader.cpp,
 * mod-instance-reset/src/mir_loader.cpp).
 */

void AddSC_dk_lowlevel();

void Addmod_dk_lowlevelScripts()
{
    AddSC_dk_lowlevel();
}
