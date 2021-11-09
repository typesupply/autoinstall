"""
To Do:
- delay between checking font and pushing to install?
- reinstall button needs to work
- allow adjusting the timer delay
- install on leaving the app
"""

import os
import weakref
import tempfile
import AppKit
import vanilla
import ezui
from lib.tools import fontInstaller
from mojo.UI import getDefault, setDefault
from mojo.events import publishEvent
from mojo.subscriber import (
    Subscriber,
    registerRoboFontSubscriber,
    registerSubscriberEvent
)
from mojo.roboFont import AllFonts, CurrentFont, OpenFont

DEBUG = ".robofontext" not in __file__.lower()

def log(*args):
    if not DEBUG:
        return
    print(*args)

# --------------
# Temp Lib Flags
# --------------

keyStub = "com.typesupply.autoInstaller."
autoInstallKey = keyStub + "autoInstall"
needsUpdateKey = keyStub + "needsUpdate"

def getTempLib(font):
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


# ----------
# Subscriber
# ----------

class AutoInstallerRoboFontSubscriber(Subscriber):

    debug = True

    def build(self):
        self.externalFonts = {}

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
        self.windowUpdateInternalFontsTable()
        self.windowClearProgressBar()
        log("< subscriber._installInternalFonts")

    # Timer

    installTimer = None
    installTimerDelay = 5

    def stopInstallTimer(self):
        if self.installTimer is not None:
            self.installTimer.invalidate()
        self.installTimer = None

    def startInstallTimer(self):
        log("> subscriber.startInstallTimer")
        self.stopInstallTimer()
        self.installTimer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            self.installTimerDelay,
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
        font = info["font"]
        if font.path in self.externalFonts:
            oldFont = self.externalFonts[font.path]
            uninstallFont(oldFont)
            del self.externalFonts[font.path]
            setFontIsAutoInstalled(font, True)
            setFontNeedsUpdate(font, True)
        self._installInternalFonts()
        self.windowUpdateInternalFontsTable()

    def fontDocumentDidClose(self, info):
        font = info["font"]
        if fontIsAutoInstalled(font):
            self._removeInternalFont(font)
            uninstallFont(font)
        self.windowUpdateInternalFontsTable()

    # Font Monitoring

    def setFontNeedsUpdate(self, font):
        log("> subscriber.setFontNeedsUpdate")
        if fontIsAutoInstalled(font):
            setFontNeedsUpdate(font, True)
        self.startInstallTimer()
        self.windowUpdateInternalFontsTable()
        log("< subscriber.setFontNeedsUpdate")

    def adjunctFontDidChangeGlyphOrder(self, info):
        font = info["font"]
        self.setFontNeedsUpdate(font)

    def adjunctFontInfoDidChange(self, info):
        font = info["font"]
        self.setFontNeedsUpdate(font)

    def adjunctFontKerningDidChange(self, info):
        kerning = info["kerning"]
        font = kerning.font
        self.setFontNeedsUpdate(font)

    def adjunctFontGroupsDidChange(self, info):
        font = info["font"]
        self.setFontNeedsUpdate(font)

    def adjunctFontFeaturesDidChange(self, info):
        font = info["font"]
        self.setFontNeedsUpdate(font)

    def adjunctFontLayersDidChangeLayer(self, info):
        font = info["font"]
        self.setFontNeedsUpdate(font)

    def adjunctFontLayersDidSetDefaultLayer(self, info):
        font = info["font"]
        self.setFontNeedsUpdate(font)

    # Menu Support

    def autoInstallerOpenWindow(self, info):
        if self.window is not None:
            return
        self.window = AutoInstallerWindowController(self)

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

    # Window Support

    window = None

    def windowUpdateInternalFontsTable(self):
        if self.window is None:
            return
        self.window.updateInternalFontsTable()

    def windowUpdateExternalFontsTable(self):
        if self.window is None:
            return
        self.window.updateExternalFontsTable()

    def addExternalFontPaths(self, paths):
        progressBar = self.windowStartProgressBar(len(paths) * (installProgressIncrements + 1))
        for path in paths:
            font = OpenFont(path, showInterface=False)
            if progressBar is not None:
                progressBar.increment()
            self.externalFonts[path] = font
            installFont(font, progressBar)
        self.windowClearProgressBar()
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

    def windowStartProgressSpinner(self):
        if self.window is None:
            return
        self.window.startProgressSpinner(count=self.installTimerDelay)

    def windowStartProgressBar(self, count):
        if self.window is None:
            return
        return self.window.startProgressBar(count=count)

    def windowClearProgressBar(self):
        if self.window is None:
            return
        self.window.startProgressBar(count=None)

# ---------
# Installer
# ---------

installProgressIncrements = 3

def installFont(font, progressBar=None):
    if progressBar is not None:
        progressBar.increment()
    app = AppKit.NSApp()
    # compile
    fontPath = tempfile.mkstemp()[1] + ".otf"
    publishEvent(
        "fontWillTestInstall",
        font=font,
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
    oldFontIdentifier = app._installedFonts.get(font)
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
            font=font
        )
        fontInstaller.uninstallFont(oldFontPath)
        if os.path.exists(oldFontPath):
            os.remove(oldFontPath)
        del app._installedFonts[font]
        doodleTestInstalledFonts = dict(getDefault("DoodleTestInstalledFonts", {}))
        del doodleTestInstalledFonts[oldFontPath]
        setDefault("DoodleTestInstalledFonts", doodleTestInstalledFonts)
        publishEvent(
            "fontDidTestDeinstall",
            font=font
        )
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
            font=font,
            format="otf",
            succes=didInstall,
            success=didInstall,
            report=report
        )
    if progressBar is not None:
        progressBar.increment()

def uninstallFont(font):
    font.testDeinstall()

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
]

for event in customEventsToRegister:
    try:
        registerSubscriberEvent(**event)
    except AssertionError:
        print(f"Already registered: {event['methodName']}")

registerRoboFontSubscriber(AutoInstallerRoboFontSubscriber)


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

        # Internal Fonts

        internalFontsTitle = dict(
            type="Label",
            text="Open Fonts",
            style="headline"
        )

        iconColumnWidth = 16
        internalFontsTable = dict(
            identifier="internalFontsTable",
            type="Table",
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
            items=[],
            showColumnTitles=False,
            height=150,
            footerDescription=[
                dict(
                    identifier="internalFontsTableReinstallButton",
                    type="PushButton",
                    text="Reinstall",
                    gravity="trailing"
                )
            ]
        )

        # External Fonts

        externalFontsTitle = dict(
            type="Label",
            text="External Fonts",
            style="headline"
        )

        externalFontsTable = dict(
            identifier="externalFontsTable",
            type="Table",
            columnDescriptions=[
                dict(
                    identifier="fileName",
                    editable=False
                )
            ],
            showColumnTitles=False,
            height=150,
            footerDescription=[
                dict(
                    identifier="externalFontsTableAddRemoveButton",
                    type="AddRemoveButton"
                ),
                dict(
                    identifier="externalFontsTableReinstallButton",
                    type="PushButton",
                    text="Reinstall",
                    gravity="trailing"
                )
            ],
            dropSettings=dict(
                pasteboardTypes=["fileURL"],
                dropCandidateCallback=self.externalFontsTableDropCandidateCallback,
                performDropCallback=self.externalFontsTablePerformDropCallback
            )
        )

        # Footer

        footerDescription = [
            dict(
                type="ProgressSpinner",
                identifier="timerProgressSpinner",
                gravity="leading"
            ),
            dict(
                type="ProgressBar",
                identifier="installerProgressBar",
                gravity="trailing"
            )
        ]

        # Window

        windowContent = dict(
            type="VerticalStack",
            contentDescriptions=[
                internalFontsTitle,
                internalFontsTable,
                dict(type="Line"),
                externalFontsTitle,
                externalFontsTable,
                dict(type="Line")
            ]
        )

        windowDescription = dict(
            type="Window",
            size=(300, 0),
            title="Probe Launcher",
            contentDescription=windowContent,
            footerDescription=footerDescription
        )
        self.w = ezui.makeItem(
            windowDescription,
            controller=self
        )

    def started(self):
        self.updateInternalFontsTable()
        self.installerProgressBar = self.w.findItem("installerProgressBar")
        self.timerProgressSpinner = self.w.findItem("timerProgressSpinner")
        # self.installerProgressBar.show(False)
        # self.timerProgressSpinner.show(False)
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
        table = self.w.findItem("internalFontsTable")
        table.set(items)

    def internalFontsTableEditCallback(self, sender):
        table = self.w.findItem("internalFontsTable")
        fonts = []
        for item in table.get():
            font = item["font"]
            autoInstall = bool(item["autoInstall"])
            fonts.append((font, autoInstall))
        self.subscriber.setInternalFontsAutoInstallStates(fonts)

    def internalFontsTableReinstallButtonCallback(self, sender):
        print("xxx internalFontsTableReinstallButtonCallback")

    spinnerTimer = None

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
        self.timerProgressSpinner.getNSProgressIndicator().setMaxValue_(count + 1)
        self.timerProgressSpinner.set(0)

    def spinnerTimerFire_(self, timer):
        info = timer.userInfo()
        value = info["value"]
        value += 1
        count = info["count"]
        self.timerProgressSpinner.set(value)
        if value == count:
            timer.invalidate()
        else:
            info["value"] = value

    def startProgressBar(self, count=None):
        self.timerProgressSpinner.set(0)
        self.installerProgressBar.set(0)
        if count is None:
            return
        self.installerProgressBar.getNSProgressIndicator().setMaxValue_(count)
        self.installerProgressBar.set(0)
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
        table = self.w.findItem("externalFontsTable")
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
            item["path"] for item in self.w.findItem("externalFontsTable").get()
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
        table = self.w.findItem("externalFontsTable")
        selection = table.getSelectedIndexes()
        items = table.get()
        paths = [
            items[i]["path"]
            for i in selection
        ]
        self.subscriber.removeExternalFontPaths(paths)

    def externalFontsTableReinstallButtonCallback(self, sender):
        print("xxx internalFontsTableReinstallButtonCallback")

if __name__ == "__main__":
    publishEvent(
        "AutoInstaller.OpenWindow"
    )

