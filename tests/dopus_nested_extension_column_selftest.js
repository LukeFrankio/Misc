/**
 * @file dopus_nested_extension_column_selftest.js
 * @brief Windows Script Host self-tests for the nested extension add-in.
 *
 * This file exercises the helper logic and the Directory Opus-facing entry
 * points in the add-in using `cscript` and simple mock objects.
 */

/**
 * @returns {Object} ActiveX FileSystemObject instance.
 */
function CreateFileSystemObject() {
    return new ActiveXObject('Scripting.FileSystemObject')
}

/**
 * @param {string} filePath Absolute path to the file to read.
 * @returns {string} Full file contents.
 */
function ReadAllText(filePath) {
    var file = CreateFileSystemObject().OpenTextFile(filePath, 1, false)

    try {
        return file.ReadAll()
    } finally {
        file.Close()
    }
}

/**
 * @param {string} message Failure message.
 */
function Fail(message) {
    throw new Error(message)
}

/**
 * @param {string} name Assertion name.
 * @param {*} actual Actual value.
 * @param {*} expected Expected value.
 */
function AssertEqual(name, actual, expected) {
    if (actual !== expected) {
        Fail(name + ': expected [' + expected + '] but received [' + actual + ']')
    }
}

/**
 * @param {string} name Assertion name.
 * @param {boolean} condition Assertion condition.
 */
function AssertTrue(name, condition) {
    if (!condition) {
        Fail(name + ': expected condition to be true')
    }
}

var fileSystemObject = CreateFileSystemObject()
var testsDirectory = fileSystemObject.GetParentFolderName(WScript.ScriptFullName)
var repositoryRoot = fileSystemObject.GetParentFolderName(testsDirectory)
var productionScriptPath = fileSystemObject.BuildPath(
    repositoryRoot,
    'dopus_nested_extension_column.js'
)

var productionScriptSource = ReadAllText(productionScriptPath)
eval(productionScriptSource)

AssertTrue(
    'GetNestedExtensionValue exists',
    typeof GetNestedExtensionValue === 'function'
)
AssertEqual(
    'compound extension is preserved',
    GetNestedExtensionValue({ name: 'hello.ini.txt', is_dir: false, ext_m: '.ini.txt' }),
    '.ini.txt'
)
AssertEqual(
    'single extension is preserved',
    GetNestedExtensionValue({ name: 'hello.txt', is_dir: false, ext_m: '.txt' }),
    '.txt'
)
AssertEqual(
    'missing extension returns empty string',
    GetNestedExtensionValue({ name: 'README', is_dir: false, ext_m: '' }),
    ''
)
AssertEqual(
    'folders return empty string',
    GetNestedExtensionValue({ name: 'archive.tar.gz', is_dir: true, ext_m: '.tar.gz' }),
    ''
)
AssertEqual(
    'arbitrary dotted filenames keep the full suffix chain',
    GetNestedExtensionValue({
        name: 'binary.instructions.md',
        is_dir: false,
        ext_m: '.md'
    }),
    '.instructions.md'
)
AssertEqual(
    'dotfiles keep the whole filename as the extension token',
    GetNestedExtensionValue({
        name: '.gitignore',
        is_dir: false,
        ext_m: ''
    }),
    '.gitignore'
)

AssertTrue('OnInit exists', typeof OnInit === 'function')
AssertTrue('OnAddColumns exists', typeof OnAddColumns === 'function')
AssertTrue(
    'OnNestedExtensionColumn exists',
    typeof OnNestedExtensionColumn === 'function'
)

var initData = {}
OnInit(initData)

AssertEqual('script display name', initData.name, 'Nested Extension Column')
AssertEqual('script version', initData.version, '1.0')
AssertEqual(
    'script description',
    initData.desc,
    'Adds a custom Directory Opus column exposing the full nested extension.'
)
AssertEqual('script default state', initData.default_enable, true)

var definedColumn = {}
var addColumnCallCount = 0

OnAddColumns({
    AddColumn: function() {
        addColumnCallCount = addColumnCallCount + 1
        return definedColumn
    }
})

AssertEqual('AddColumn invoked once', addColumnCallCount, 1)
AssertEqual('column raw name', definedColumn.name, 'NestedExtension')
AssertEqual('column label', definedColumn.label, 'Nested Extension')
AssertEqual(
    'column callback method',
    definedColumn.method,
    'OnNestedExtensionColumn'
)
AssertEqual('column type', definedColumn.type, '')

var fileColumnData = {
    item: {
        name: 'archive.tar.gz',
        is_dir: false,
        ext_m: '.tar.gz'
    }
}

OnNestedExtensionColumn(fileColumnData)
AssertEqual('file callback value', fileColumnData.value, '.tar.gz')

var folderColumnData = {
    item: {
        name: 'folder.tar.gz',
        is_dir: true,
        ext_m: '.zip'
    }
}

OnNestedExtensionColumn(folderColumnData)
AssertEqual('folder callback value', folderColumnData.value, '')

WScript.Echo('All nested extension self-tests passed')
