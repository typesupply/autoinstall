# Auto Install

## Main Window

### Open Fonts

This list shows all open fonts. If you want one of the fonts to be auto installed after changes are detected, check it. The indicator will show you if the installation is up to date or an installation is pending. If you want the fonts to be updated right now, press the "Update" button.

### External Fonts

Drag UFOs from the Finder to this list and they will be installed. Use the plus/minus buttons to add/remove UFOs. This does not monitor the fonts for changes made outside of RoboFont, so if you make a change to a font and need to update it, press the "Update" button. If you want to open a font in the list, double click it.

### Designspaces

Drag designspaces from the Finder to this list and any fonts they produce will be installed. Use the plus/minus buttons to add/remove designspaces. This does not monitor the designspaces or the sources in the designspaces for changes, so if you make a change to a designspace or source and need to update it, press the "Update" button. If you want to open a designspace in the list in Design Space Editor, double click it. During the build of the designspace, if Prepolator is availabe it will be used to automatically correct resolvable incompatibilities in glyphs and it will try to find the correct ordering for glyphs with low compatibility confidence.

### Footer

When a change is detected, a timer will appear showing how long it will be before the font is compiled and installed. While a font is being installed, a progress bar will show you the, you guessed it, progress.

## Menu Items

You don't have to see the window. You can use the menu items to add fonts that you want to install.

## Settings

- *seconds after a change* This controls how long the delay is between user inactivity a change will occur. If you don't want it to update automatically after changes, set the value to zero.
- *after saving the font* This will trigger an installation update when a font is saved.
- *after exiting RoboFont* This will trigger an installation when you switch from RoboFont to another app.