import os
import weakref
import uuid
import AppKit
import vanilla
import ezui
from lib.tools import fontInstaller
from lib.settings import applicationTestInstallRootPath
from mojo.UI import getDefault, setDefault
from mojo.events import (
    publishEvent,
    addObserver,
    removeObserver
)
from mojo.subscriber import (
    Subscriber,
    registerRoboFontSubscriber,
    registerGlyphEditorSubscriber,
    registerSubscriberEvent
)
from mojo.extensions import (
    registerExtensionDefaults,
    getExtensionDefault,
    setExtensionDefault,
    removeExtensionDefault
)
from mojo.events import postEvent
from mojo.roboFont import AllFonts, CurrentFont, OpenFont

extensionIdentifier = "com.typesupply.AutoInstall"

# ---------
# Debugging
# ---------

DEBUG = ".robofontext" not in __file__.lower()
DEBUG = False

indent = ""

def log(*args):
    if not DEBUG:
        return
    global indent
    if args:
        a = args[0]
        if isinstance(a, str):
            if a.startswith(">"):
                indent += " "
    print(indent, *args)
    if args:
        a = args[0]
        if isinstance(a, str):
            if a.startswith("<"):
                indent = indent[:-1]

# --------------
# Temp Lib Flags
# --------------

keyStub = extensionIdentifier + "."
autoInstallKey = keyStub + "autoInstall"
needsUpdateKey = keyStub + "needsUpdate"

def getTempLib(font):
    if font is None:
        return {}
    tempLib = font.asDefcon().tempLib
    return tempLib

def fontIsAutoInstalled(font):
    tempLib = getTempLib(font)
    return tempLib.get(autoInstallKey, False)

def setFontIsAutoInstalled(font, state):
    tempLib = getTempLib(font)
    tempLib[autoInstallKey] = state
    if not state:
        tempLib[needsUpdateKey] = False

def fontNeedsUpdate(font):
    tempLib = getTempLib(font)
    return tempLib.get(needsUpdateKey, False)

def setFontNeedsUpdate(font, state):
    tempLib = getTempLib(font)
    tempLib[needsUpdateKey] = state


# --------
# Defaults
# --------

defaults = dict(
    installAfterChangeDelay=5,
    installAfterSave=False,
    installAfterAppExit=True
)

defaults = {
    extensionIdentifier + "." + key : value
    for key, value in defaults.items()
}

registerExtensionDefaults(defaults)

# -------------------
# RoboFont Subscriber
# -------------------

class AutoInstallerRoboFontSubscriber(Subscriber):

    debug = DEBUG

    def build(self):
        self.externalFonts = {}
        self.loadDefaults()
        addObserver(
            self,
            "extensionDefaultsChanged",
            extensionIdentifier + ".defaultsChanged"
        )

    def started(self):
        log("> subscriber.started")
        for font in AllFonts():
            if fontIsAutoInstalled(font):
                setFontNeedsUpdate(font, True)
                self._addInternalFont(font)
        self._installInternalFonts()
        log("< subscriber.started")

    def destroy(self):
        log("> subscriber.destroy")
        self.stopInstallTimer()
        for font in AllFonts():
            if fontIsAutoInstalled(font):
                uninstallFont(font)
        for path, font in self.externalFonts.items():
            uninstallFont(font)
            setFontIsAutoInstalled(font, False)
            font.close()
        self.externalFonts = {}
        log("< subscriber.destroy")

    # defaults

    def loadDefaults(self):
        self.installAfterChangeDelay = getExtensionDefault(extensionIdentifier + ".installAfterChangeDelay")
        self.installAfterSave = getExtensionDefault(extensionIdentifier + ".installAfterSave")
        self.installAfterAppExit = getExtensionDefault(extensionIdentifier + ".installAfterAppExit")
        self.resetInstallTimer()

    def extensionDefaultsChanged(self, event):
        self.loadDefaults()

    # Install

    def _installInternalFonts(self):
        log("> subscriber._installInternalFonts")
        toInstall = []
        for font in AllFonts():
            if not fontIsAutoInstalled(font):
                continue
            if not fontNeedsUpdate(font):
                continue
            toInstall.append(font)
        if toInstall:
            progressBar = self.windowStartProgressBar(len(toInstall) * installProgressIncrements)
            for font in toInstall:
                installFont(font, progressBar)
                setFontNeedsUpdate(font, False)
            self.windowClearProgressBar()
        self.windowUpdateInternalFontsTable()
        self.windowClearProgressSpinner()
        self.windowClearProgressBar()
        log("< subscriber._installInternalFonts")

    def installInternalFontsNow(self, fonts):
        self.stopInstallTimer()
        self.windowClearProgressSpinner()
        for font in fonts:
            setFontNeedsUpdate(font, True)
        self._installInternalFonts()

    # Timer

    installTimer = None

    def resetInstallTimer(self):
        log("> subscriber.resetInstallTimer")
        if self.installTimer is not None:
            self.startInstallTimer()
        log("< subscriber.resetInstallTimer")

    def stopInstallTimer(self):
        log("> subscriber.stopInstallTimer")
        if self.installTimer is not None:
            self.installTimer.invalidate()
        self.installTimer = None
        log("< subscriber.stopInstallTimer")

    def startInstallTimer(self):
        delay = self.installAfterChangeDelay
        if not delay:
            return
        log("> subscriber.startInstallTimer")
        self.stopInstallTimer()
        self.installTimer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            delay,
            self,
            "installTimerFire:",
            None,
            False
        )
        self.windowStartProgressSpinner()
        log("< subscriber.startInstallTimer")

    def installTimerFire_(self, timer):
        log("> subscriber.installTimerFire_")
        self.installTimer = None
        self._installInternalFonts()
        log("< subscriber.installTimerFire_")

    # Document Monitoring

    def fontDocumentDidOpen(self, info):
        log("> subscriber.fontDocumentDidOpen")
        font = info["font"]
        if font.path in self.externalFonts:
            oldFont = self.externalFonts[font.path]
            uninstallFont(oldFont)
            del self.externalFonts[font.path]
            setFontIsAutoInstalled(font, True)
            setFontNeedsUpdate(font, True)
        self._installInternalFonts()
        self.windowUpdateInternalFontsTable()
        self.windowUpdateExternalFontsTable()
        log("< subscriber.fontDocumentDidOpen")

    def fontDocumentDidClose(self, info):
        log("> subscriber.fontDocumentDidClose")
        font = info["font"]
        if fontIsAutoInstalled(font):
            self._removeInternalFont(font)
            uninstallFont(font)
        self.windowUpdateInternalFontsTable()
        log("< subscriber.fontDocumentDidClose")

    def fontDocumentDidSave(self, info):
        if not self.installAfterSave:
            return
        log("> subscriber.fontDocumentDidSave")
        self._installInternalFonts()
        log("< subscriber.fontDocumentDidSave")

    # Font Monitoring

    def setFontNeedsUpdate(self, font):
        if font is None:
            return
        log("> subscriber.setFontNeedsUpdate")
        if fontIsAutoInstalled(font):
            setFontNeedsUpdate(font, True)
        self.startInstallTimer()
        self.windowUpdateInternalFontsTable()
        log("< subscriber.setFontNeedsUpdate")

    def adjunctFontDidChangeGlyphOrder(self, info):
        log("> subscriber.adjunctFontDidChangeGlyphOrder")
        font = info["font"]
        self.setFontNeedsUpdate(font)
        log("< subscriber.adjunctFontDidChangeGlyphOrder")

    def adjunctFontInfoDidChange(self, info):
        log("> subscriber.adjunctFontInfoDidChange")
        font = info["font"]
        self.setFontNeedsUpdate(font)
        log("< subscriber.adjunctFontInfoDidChange")

    def adjunctFontKerningDidChange(self, info):
        log("> subscriber.adjunctFontKerningDidChange")
        font = info["font"]
        self.setFontNeedsUpdate(font)
        log("< subscriber.adjunctFontKerningDidChange")

    def adjunctFontGroupsDidChange(self, info):
        log("> subscriber.adjunctFontGroupsDidChange")
        font = info["font"]
        self.setFontNeedsUpdate(font)
        log("< subscriber.adjunctFontGroupsDidChange")

    def adjunctFontFeaturesDidChange(self, info):
        log("> subscriber.adjunctFontFeaturesDidChange")
        font = info["font"]
        self.setFontNeedsUpdate(font)
        log("< subscriber.adjunctFontFeaturesDidChange")

    def adjunctFontLayersDidChangeLayer(self, info):
        log("> subscriber.adjunctFontLayersDidChangeLayer")
        font = info["font"]
        self.setFontNeedsUpdate(font)
        log("< subscriber.adjunctFontLayersDidChangeLayer")

    def adjunctFontLayersDidSetDefaultLayer(self, info):
        log("> subscriber.adjunctFontLayersDidSetDefaultLayer")
        font = info["font"]
        self.setFontNeedsUpdate(font)
        log("< subscriber.adjunctFontLayersDidSetDefaultLayer")

    # App Monitoring

    def roboFontWillResignActive(self, info):
        if not self.installAfterAppExit:
            return
        log("> subscriber.roboFontWillResignActive")
        self.stopInstallTimer()
        self.installTimerFire_(None)
        log("< subscriber.roboFontWillResignActive")

    # Glyph Editor Activity

    def autoInstallerGlyphEditorActivity(self, info):
        log("> subscriber.autoInstallerGlyphEditorActivity")
        self.resetInstallTimer()
        log("< subscriber.autoInstallerGlyphEditorActivity")

    # Menu Support

    def autoInstallerOpenWindow(self, info):
        if self.window is not None:
            return
        self.window = AutoInstallerWindowController(self)
        self.windowUpdateInternalFontsTable()
        self.windowUpdateExternalFontsTable()

    def autoInstallerAddCurrentFont(self, info):
        self.setInternalFontsAutoInstallStates([(CurrentFont(), True)])

    def autoInstallerAddOpenFonts(self, info):
        fonts = [(font, True) for font in AllFonts()]
        self.setInternalFontsAutoInstallStates(fonts)

    def autoInstallerAddExternalFonts(self, info):
        paths = vanilla.dialogs.getFile(
            allowsMultipleSelection=True,
            fileTypes=["ufo", "ufoz"]
        )
        if paths:
            self.addExternalFontPaths(paths)

    def autoInstallerOpenDefaultsWindow(self, info):
        if self.defaultsWindow is not None:
            return
        self.defaultsWindow = AutoInstallerDefaultsWindowController(self)

    # Window Support

    window = None
    defaultsWindow = None

    def windowUpdateInternalFontsTable(self):
        if self.window is None:
            return
        self.window.updateInternalFontsTable()

    def windowUpdateExternalFontsTable(self):
        if self.window is None:
            return
        self.window.updateExternalFontsTable()

    def addExternalFontPaths(self, paths):
        self.installExternalFontsNow(paths)
        self.windowUpdateExternalFontsTable()

    def getExternalFontPaths(self):
        return list(self.externalFonts.keys())

    def removeExternalFontPaths(self, paths):
        for path in paths:
            font = self.externalFonts.pop(path)
            uninstallFont(font)
            font.close()
        self.windowUpdateExternalFontsTable()

    def setInternalFontsAutoInstallStates(self, fonts):
        for font, autoInstall in fonts:
            if not autoInstall:
                if fontIsAutoInstalled(font):
                    self._removeInternalFont(font)
                    uninstallFont(font)
                setFontIsAutoInstalled(font, False)
                setFontNeedsUpdate(font, False)
            else:
                if not fontIsAutoInstalled(font):
                    setFontIsAutoInstalled(font, True)
                    setFontNeedsUpdate(font, True)
                    self._addInternalFont(font)
        self._installInternalFonts()

    def _addInternalFont(self, font):
        self.addAdjunctObjectToObserve(font)
        self.addAdjunctObjectToObserve(font.info)
        self.addAdjunctObjectToObserve(font.features)
        self.addAdjunctObjectToObserve(font.kerning)
        self.addAdjunctObjectToObserve(font.groups)
        self.addAdjunctObjectToObserve(font.asDefcon().layers)

    def _removeInternalFont(self, font):
        self.removeObservedAdjunctObject(font)
        self.removeObservedAdjunctObject(font.info)
        self.removeObservedAdjunctObject(font.features)
        self.removeObservedAdjunctObject(font.kerning)
        self.removeObservedAdjunctObject(font.groups)
        self.removeObservedAdjunctObject(font.asDefcon().layers)

    def windowClearProgressSpinner(self):
        if self.window is None:
            return
        self.window.clearProgressSpinner()

    def windowStartProgressSpinner(self):
        if self.window is None:
            return
        delay = self.installAfterChangeDelay
        if not delay:
            return
        self.window.startProgressSpinner(count=delay)

    def windowClearProgressBar(self):
        if self.window is None:
            return
        self.window.clearProgressBar()

    def windowStartProgressBar(self, count):
        if self.window is None:
            return
        return self.window.startProgressBar(count=count)

    # External Fonts

    def installExternalFontsNow(self, paths):
        progressBar = self.windowStartProgressBar(len(paths) * (installProgressIncrements + 1))
        for path in paths:
            if progressBar is not None:
                progressBar.increment()
            if path not in self.externalFonts:
                self.externalFonts[path] = OpenFont(path, showInterface=False)
            font = self.externalFonts[path]
            installFont(font, progressBar)
        self.windowClearProgressBar()

# -----------------------
# Glyph Editor Subscriber
# -----------------------

class AutoInstallerGlyphEditorSubscriber(Subscriber):

    debug = DEBUG

    def genericActivity(self, info):
        publishEvent(
            "AutoInstaller.GlyphEditorActivity"
        )

    glyphEditorDidKeyDown = genericActivity
    glyphEditorDidKeyUp = genericActivity
    glyphEditorDidChangeModifiers = genericActivity
    glyphEditorDidMouseDown = genericActivity
    glyphEditorDidMouseUp = genericActivity
    glyphEditorDidMouseDrag = genericActivity
    glyphEditorDidRightMouseDown = genericActivity
    glyphEditorDidRightMouseUp = genericActivity
    glyphEditorDidRightMouseDrag = genericActivity
    glyphEditorDidScale = genericActivity
    glyphEditorWillScale = genericActivity
    glyphEditorDidCopy = genericActivity
    glyphEditorDidCopyAsComponent = genericActivity
    glyphEditorDidCut = genericActivity
    glyphEditorDidPaste = genericActivity
    glyphEditorDidPasteSpecial = genericActivity
    glyphEditorDidDelete = genericActivity
    glyphEditorDidSelectAll = genericActivity
    glyphEditorDidSelectAllAlternate = genericActivity
    glyphEditorDidSelectAllControl = genericActivity
    glyphEditorDidDeselectAll = genericActivity
    glyphEditorDidUndo = genericActivity
    glyphEditorGlyphDidChangeSelection = genericActivity



# ---------
# Installer
# ---------

installProgressIncrements = 3

def installFont(font, progressBar=None):
    if progressBar is not None:
        progressBar.increment()
    app = AppKit.NSApp()
    # compile
    fontPath = os.path.join(
        applicationTestInstallRootPath,
        f"{font.info.familyName}-{font.info.styleName}_{uuid.uuid1()}.otf"
    )

    publishEvent(
        "fontWillTestInstall",
        font=font.asDefcon(),
        format="otf"
    )
    didGenerate = True
    try:
        report = font.asDefcon().generate(
            fontPath,
            progressBar=None,
            testInstall=True,
            decompose="False",
            checkOutlines=True,
            autohint=False,
            releaseMode=False,
            glyphOrder=font.glyphOrder
        )
    except Exception:
        didGenerate = False
        print(f"Error generating {font.path}.")
    if progressBar is not None:
        progressBar.increment()
    # remove old
    uninstallFont(font)
    if progressBar is not None:
        progressBar.increment()
    # install new
    if didGenerate:
        didInstall, report = fontInstaller.installFont(fontPath, False)
        if didInstall:
            fontIdentifier = dict(
                fontPath=fontPath,
                name=f"{font.info.familyName} {font.info.styleName}"
            )
            app._installedFonts[font.asDefcon()] = fontIdentifier
            doodleTestInstalledFonts = dict(getDefault("DoodleTestInstalledFonts", {}))
            doodleTestInstalledFonts[fontPath] = fontIdentifier
            setDefault("DoodleTestInstalledFonts", doodleTestInstalledFonts)
        else:
            print("Error installing {font.path}.")
            print(report)
        publishEvent(
            "fontDidTestInstall",
            font=font.asDefcon(),
            format="otf",
            succes=didInstall,
            success=didInstall,
            report=report
        )
    if progressBar is not None:
        progressBar.increment()

def uninstallFont(font):
    app = AppKit.NSApp()
    oldFontIdentifier = app._installedFonts.get(font.asDefcon())
    if oldFontIdentifier is None:
        oldFontIdentifier = {}
        name = f"{font.info.familyName} {font.info.styleName}"
        for font, info in app._installedFonts.items():
            if info.get("name", "") == name:
                oldFontIdentifier = info
                break
    oldFontPath = oldFontIdentifier.get("fontPath")
    if oldFontPath is not None:
        publishEvent(
            "fontWillTestDeinstall",
            font=font.asDefcon()
        )
        fontInstaller.uninstallFont(oldFontPath)
        if os.path.exists(oldFontPath):
            os.remove(oldFontPath)
        del app._installedFonts[font.asDefcon()]
        doodleTestInstalledFonts = dict(getDefault("DoodleTestInstalledFonts", {}))
        del doodleTestInstalledFonts[oldFontPath]
        setDefault("DoodleTestInstalledFonts", doodleTestInstalledFonts)
        publishEvent(
            "fontDidTestDeinstall",
            font=font.asDefcon()
        )

# -------------
# Custom Events
# -------------

def genericEventRegisterDict(**kwargs):
    default = dict(
        subscriberEventName=None,
        methodName=None,
        lowLevelEventNames=[],
        dispatcher="roboFont",
        eventInfoExtractionFunction=None,
        delay=0
    )
    default.update(kwargs)
    if not default["lowLevelEventNames"]:
        default["lowLevelEventNames"] = [default["subscriberEventName"]]
    if not default["methodName"]:
        name = default["subscriberEventName"].replace(".", "")
        default["methodName"] = name[0].lower() + name[1:]
    return default

customEventsToRegister = [
    genericEventRegisterDict(
        subscriberEventName="AutoInstaller.OpenWindow"
    ),
    genericEventRegisterDict(
        subscriberEventName="AutoInstaller.AddCurrentFont"
    ),
    genericEventRegisterDict(
        subscriberEventName="AutoInstaller.AddOpenFonts"
    ),
    genericEventRegisterDict(
        subscriberEventName="AutoInstaller.AddExternalFonts"
    ),
    genericEventRegisterDict(
        subscriberEventName="AutoInstaller.GlyphEditorActivity"
    ),
    genericEventRegisterDict(
        subscriberEventName="AutoInstaller.OpenDefaultsWindow"
    ),
]

for event in customEventsToRegister:
    try:
        registerSubscriberEvent(**event)
    except AssertionError:
        log(f"Already registered: {event['methodName']}")

registerRoboFontSubscriber(AutoInstallerRoboFontSubscriber)
registerGlyphEditorSubscriber(AutoInstallerGlyphEditorSubscriber)


# ------
# Window
# ------

class AutoInstallerWindowController(ezui.WindowController):

    _subscriber = None

    def _get_subscriber(self):
        if self._subscriber is not None:
            return self._subscriber()

    subscriber = property(_get_subscriber)

    def build(self, subscriber):
        if subscriber is not None:
            self._subscriber = weakref.ref(subscriber)

        windowContent = """
        !§ Open Fonts

        |----------------------|    @internalFontsTable
        | [ ] O Name.ufo       |
        | [X] O Name.ufo       |
        |                      |
        |----------------------|

        ------------------------

        !§ External Fonts

        |----------------------|    @externalFontsTable
        | Name.ufo             |
        | Name.ufo             |
        |                      |
        |----------------------|

        ------------------------
        """

        internalFontsTableFooter = """
        (Update)                    @internalFontsTableReinstallButton
        """

        externalFontsTableFooter = """
        (+-)                        @externalFontsTableAddRemoveButton
        (Update)                    @externalFontsTableReinstallButton
        """

        windowFooter = """
        %                           @timerProgressSpinner
        %%---------                 @installerProgressBar
        """

        iconColumnWidth = 16
        descriptionData = dict(

            # Internal Fonts

            internalFontsTable=dict(
                height=150,
                showColumnTitles=False,
                columnDescriptions=[
                    dict(
                        identifier="autoInstall",
                        width=iconColumnWidth,
                        cellDescription=dict(
                            cellType="Checkbox"
                        ),
                        editable=True
                    ),
                    dict(
                        identifier="installStatus",
                        width=iconColumnWidth,
                        cellDescription=dict(
                            cellType="Image"
                        ),
                        editable=False
                    ),
                    dict(
                        identifier="fileName",
                        editable=False
                    )
                ],
                footer=internalFontsTableFooter
            ),

            # External Fonts

            externalFontsTable = dict(
                height=150,
                showColumnTitles=False,
                columnDescriptions=[
                    dict(
                        identifier="fileName",
                        editable=False
                    )
                ],
                footer=externalFontsTableFooter,
                dropSettings=dict(
                    pasteboardTypes=["fileURL"],
                    dropCandidateCallback=self.externalFontsTableDropCandidateCallback,
                    performDropCallback=self.externalFontsTablePerformDropCallback
                )
            )
        )

        self.w = ezui.EZWindow(
            identifier=extensionIdentifier + ".MainWindow",
            title="Auto Install",
            size=(300, "auto"),
            content=windowContent,
            footer=windowFooter,
            descriptionData=descriptionData,
            controller=self
        )

    def started(self):
        self.updateInternalFontsTable()
        self.installerProgressBar = self.w.getItem("installerProgressBar")
        self.timerProgressSpinner = self.w.getItem("timerProgressSpinner")
        self.installerProgressBar.show(False)
        self.timerProgressSpinner.show(False)
        self.w.open()

    def destroy(self):
        self._subscriber = None

    def windowWillClose(self, sender):
        self.subscriber.window = None

    # Internal Fonts

    def updateInternalFontsTable(self):
        items = []
        for font in AllFonts():
            if font.path is None:
                continue
            status = AppKit.NSImageNameStatusNone
            if fontIsAutoInstalled(font):
                status = AppKit.NSImageNameStatusAvailable
                if fontNeedsUpdate(font):
                    status = AppKit.NSImageNameStatusPartiallyAvailable
            item = dict(
                font=font,
                fileName=os.path.basename(font.path),
                autoInstall=fontIsAutoInstalled(font),
                installStatus=ezui.makeImage(
                    imageName=status
                )
            )
            items.append(item)
        table = self.w.getItem("internalFontsTable")
        table.set(items)

    def internalFontsTableEditCallback(self, sender):
        table = self.w.getItem("internalFontsTable")
        fonts = []
        for item in table.get():
            font = item["font"]
            autoInstall = bool(item["autoInstall"])
            fonts.append((font, autoInstall))
        self.subscriber.setInternalFontsAutoInstallStates(fonts)

    def internalFontsTableReinstallButtonCallback(self, sender):
        table = self.w.getItem("internalFontsTable")
        items = table.getSelectedItems()
        if not items:
            items = table.get()
        fonts = [item["font"] for item in items]
        if fonts:
            self.subscriber.installInternalFontsNow(fonts)

    spinnerTimer = None

    def clearProgressSpinner(self):
        if self.spinnerTimer is not None:
            self.spinnerTimer.invalidate()
        self.timerProgressSpinner.show(False)
        self.timerProgressSpinner.set(0)
        self.spinnerTimer = None

    def startProgressSpinner(self, count=None):
        self.timerProgressSpinner.set(0)
        if count is None:
            return
        if self.spinnerTimer is not None:
            self.spinnerTimer.invalidate()
        self.spinnerTimer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1,
            self,
            "spinnerTimerFire:",
            dict(value=0, count=count),
            True
        )
        self.timerProgressSpinner.getNSProgressIndicator().setMaxValue_(count)
        self.timerProgressSpinner.set(0)
        self.timerProgressSpinner.show(True)

    def spinnerTimerFire_(self, timer):
        info = timer.userInfo()
        value = info["value"]
        value += 1
        count = info["count"]
        self.timerProgressSpinner.set(value)
        if value == count:
            timer.invalidate()
            value = 0
        info["value"] = value

    def clearProgressBar(self):
        self.installerProgressBar.set(0)
        self.installerProgressBar.show(False)

    def startProgressBar(self, count=None):
        self.installerProgressBar.set(0)
        if count is None:
            return
        self.installerProgressBar.getNSProgressIndicator().setMaxValue_(count)
        self.installerProgressBar.set(0)
        self.installerProgressBar.show(True)
        return self.installerProgressBar

    # External Fonts

    def updateExternalFontsTable(self):
        items = []
        for path in self.subscriber.getExternalFontPaths():
            item = dict(
                path=path,
                fileName=os.path.basename(path)
            )
            items.append(item)
        table = self.w.getItem("externalFontsTable")
        table.set(items)

    def externalFontsTableDropCandidateCallback(self, info):
        paths = self._normalizeDroppedItems(info)
        if not paths:
            return "none"
        return "link"

    def externalFontsTablePerformDropCallback(self, info):
        paths = self._normalizeDroppedItems(info)
        self.subscriber.addExternalFontPaths(paths)
        return True

    def _normalizeDroppedItems(self, info):
        sender = info["sender"]
        items = info["items"]
        items = sender.getDropItemValues(items)
        paths = [
            item.path() for item in items
        ]
        return self._normalizeSelectedPaths(paths)

    def _normalizeSelectedPaths(self, paths):
        openFonts = [
            font.path for font in AllFonts()
        ]
        externalFonts = [
            item["path"] for item in self.w.getItem("externalFontsTable").get()
        ]
        paths = [
            path for path in paths
            if os.path.splitext(path)[-1].lower() in (".ufo", ".ufoz")
        ]
        paths = [
            path for path in paths
            if path not in openFonts
            and path not in externalFonts
        ]
        return paths

    def externalFontsTableAddRemoveButtonAddCallback(self, sender):
        self.showGetFile(
            ["ufo", "ufoz"],
            self._externalFontsTableGetFileCallback,
            allowsMultipleSelection=True
        )

    def _externalFontsTableGetFileCallback(self, paths):
        paths = self._normalizeSelectedPaths(paths)
        self.subscriber.addExternalFontPaths(paths)

    def externalFontsTableAddRemoveButtonRemoveCallback(self, sender):
        table = self.w.getItem("externalFontsTable")
        selection = table.getSelectedIndexes()
        items = table.get()
        paths = [
            items[i]["path"]
            for i in selection
        ]
        self.subscriber.removeExternalFontPaths(paths)

    def externalFontsTableReinstallButtonCallback(self, sender):
        table = self.w.getItem("externalFontsTable")
        items = table.getSelectedItems()
        if not items:
            items = table.get()
        paths = [item["path"] for item in items]
        if paths:
            self.subscriber.installExternalFontsNow(paths)


# ------------
# Prefs Window
# ------------

class AutoInstallerDefaultsWindowController(ezui.WindowController):

    def _get_subscriber(self):
        if self._subscriber is not None:
            return self._subscriber()

    subscriber = property(_get_subscriber)

    def build(self, subscriber):
        if subscriber is not None:
            self._subscriber = weakref.ref(subscriber)

        extensionIdentifierLength = len(extensionIdentifier) + 1
        settings = {
            key[extensionIdentifierLength:] : getExtensionDefault(key)
            for key in defaults.keys()
        }

        content = """
        !§ Update Install
        [___] seconds after a change    @installAfterChangeDelay
        [ ] after saving the font       @installAfterSave
        - # temp hack
        [ ] after exiting RoboFont      @installAfterAppExit
        """

        descriptionData = dict(
            installAfterChangeDelay=dict(
                width=185,
                value=settings["installAfterChangeDelay"],
                valueType="integer"
            ),
            installAfterSave=dict(
                value=settings["installAfterSave"]
            ),
            installAfterAppExit=dict(
                value=settings["installAfterAppExit"]
            )
        )
        self.w = ezui.EZWindow(
            identifier=extensionIdentifier + ".DefaultsWindow",
            size="auto",
            content=content,
            descriptionData=descriptionData,
            controller=self
        )

    def started(self):
        self.w.open()

    def destroy(self):
        self._subscriber = None

    def windowWillClose(self, sender):
        self.subscriber.defaultsWindow = None

    def storeSettings(self):
        settings = self.w.getItemValues()
        if settings["installAfterChangeDelay"] is None:
            return
        for key, value in settings.items():
            key = extensionIdentifier + "." + key
            setExtensionDefault(key, value)
        postEvent(
            extensionIdentifier + ".defaultsChanged"
        )

    def installAfterChangeDelayCallback(self, sender):
        self.storeSettings()

    def installAfterSaveCallback(self, sender):
        self.storeSettings()

    def installAfterAppExitCallback(self, sender):
        self.storeSettings()


if __name__ == "__main__":
    publishEvent(
        "AutoInstaller.OpenWindow"
    )