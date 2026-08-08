/*
 * mod-autolearn -- module entry point.
 *
 * THIS MODULE HAS NO C++ BEHAVIOUR ON PURPOSE. Everything it does is one SQL migration under
 * data/sql/db-world/base/. This translation unit exists only because the build refuses to ship a
 * code-less module, in two separate places:
 *
 *   1. GetModuleSourceList (src/cmake/macros/ConfigureModules.cmake:32-46) walks modules/ and
 *      keeps a directory ONLY if <module>/src is a directory (line 41). A module with no src/ is
 *      dropped from MODULES_MODULE_LIST entirely -- which also drops it from AC_MODULES_LIST
 *      (modules/CMakeLists.txt:352,371), and UpdateFetcher only looks for module SQL under the
 *      names in that list (UpdateFetcher.cpp:163-165). No src/, no migration. Silently.
 *
 *   2. ConfigureScriptLoader (modules/CMakeLists.txt:144-181) then generates a forward declaration
 *      and an unconditional call to Add${DirectoryName with - replaced by _}Scripts() into
 *      ModulesLoader.cpp:
 *
 *          mod-autolearn  ->  mod_autolearn  ->  Addmod_autolearnScripts()
 *
 *      so that symbol must exist or the link fails at the very end of a 30-minute build.
 *      Renaming build/modules/mod-autolearn/ means renaming this function too.
 *
 * Registering no script is legal and costs nothing at runtime: ScriptMgr never hears about this
 * module, so there is no hook to fire, no per-login work, and nothing to get wrong. If this module
 * ever grows real behaviour, note the fork's naming rule -- every PlayerScript virtual here is
 * OnPlayerXxx, not OnXxx, and the wrong name compiles silently and never fires.
 */

void Addmod_autolearnScripts()
{
}
