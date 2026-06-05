/**
 * @file dopus_nested_extension_column.js
 * @brief Directory Opus nested extension helper and custom column add-in.
 *
 * This script is written for the native Directory Opus JScript host. It keeps
 * the core nested-extension selection logic in a tiny helper so the behavior
 * can also be exercised through Windows Script Host self-tests.
 */

/**
 * Returns the nested or compound extension for an Item-like object.
 *
 * ✨ PURE FUNCTION ✨
 *
 * This function is pure because it only inspects the provided item-like value
 * and returns a derived string. It does not read from the file system, mutate
 * input state, or interact with Directory Opus directly.
 *
 * @param {Object} item Directory Opus Item-like object with `name`, `is_dir`,
 * and `ext_m` properties.
 * @returns {string} Full nested extension chain, or an empty string for
 * folders and extensionless items.
 */
function GetNestedExtensionValue(item) {
    var fileName
    var firstDotIndex

    if (!item || item.is_dir) {
        return ''
    }

    fileName = item.name

    if (typeof fileName === 'string') {
        firstDotIndex = fileName.indexOf('.')

        if (firstDotIndex >= 0) {
            return fileName.substring(firstDotIndex)
        }
    }

    return item.ext_m || ''
}

/**
 * Initializes the script add-in metadata for Directory Opus.
 *
 * ⚠️ IMPURE FUNCTION ⚠️
 *
 * This function is impure because it mutates the `initData` object supplied by
 * the Directory Opus host to describe the add-in.
 *
 * @param {Object} initData ScriptInitData-like object supplied by Directory
 * Opus.
 */
function OnInit(initData) {
    initData.name = 'Nested Extension Column'
    initData.version = '1.0'
    initData.desc = 'Adds a custom Directory Opus column exposing the full nested extension.'
    initData.default_enable = true
}

/**
 * Registers the custom Directory Opus column.
 *
 * ⚠️ IMPURE FUNCTION ⚠️
 *
 * This function is impure because it calls into the host-provided column
 * registration API and mutates the returned column definition object.
 *
 * @param {Object} addColData AddColData-like object supplied by Directory
 * Opus.
 */
function OnAddColumns(addColData) {
    var column = addColData.AddColumn()

    column.name = 'NestedExtension'
    column.label = 'Nested Extension'
    column.method = 'OnNestedExtensionColumn'
    column.type = ''
}

/**
 * Supplies the visible value for the nested extension column.
 *
 * ⚠️ IMPURE FUNCTION ⚠️
 *
 * This function is impure because it mutates the host-provided
 * `scriptColData` object to return the column value back to Directory Opus.
 *
 * @param {Object} scriptColData ScriptColumnData-like object containing the
 * current item and the output `value` field.
 */
function OnNestedExtensionColumn(scriptColData) {
    scriptColData.value = GetNestedExtensionValue(scriptColData.item)
}
