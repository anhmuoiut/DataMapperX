# Changelog

Each release's notes are shown to users in the update dialog, so write them for the people who use the app.
A release cannot be published unless its version has a section here.

## [1.2.0] - 2026-10-28

### New
- **Two clear steps: Select, then Review & Export.** The window now follows your work from left to right. Step 1 is the Source card with the two component lists. Step 2 shows the data as it will be exported before you save it, so you can check it first instead of opening Excel to find out.
- **Limits beside the data.** Step 2 has a *Limits* panel with every selected component's Min, Max and Unit (the same limits the Excel file lists). Click a row of the table to see that row's values next to them; a value outside its limits is marked ▲ or ▼.
- **Checks before you export.** Chips under the table sum up the samples found, the files per sample, the empty cells and the rows with a value outside its limits. *Export Excel…* stays disabled while a sample has the wrong number of files, and the step bar warns about it before you get there.
- **Add and remove with one click.** Every available component has a **+** button and shows its Min and Max; every selected component has a **×** button (red when you point at it). The old *Remove* button is gone.
- **Set up a new log format from an example file.** In *Manage profiles → New*, pick one example log and DataMapperX works out where the data is, with no regular expressions. For Excel logs it finds the results table, its columns and the serial number cell from the headings. For text logs it recognises i3070 logs, and for any other format you select the text that changes and press *Component*, *Measured value*, *Min*… to teach it. Everything it reads is coloured on the sample, a table shows the result, and it checks your settings on the other files in the folder. Regular expressions are still available under *Advanced*.
- **EOL logs are supported out of the box** (new *EOL Test Log* profile). They could not be read before because their serial numbers do not look like `VSE…`.
- **The right profile is suggested.** If a scan finds nothing but another profile can read that folder, the app offers to switch and scan again.
- **Automatic updates.** DataMapperX checks GitHub for a newer version when it starts and offers to install it with one click. The download is verified before it replaces the running program.
- **Real data preview.** The review shows the exact table that will be exported (values, not just file names). Samples with the wrong number of files are shown in red and missing values in amber.
- **Dark mode**, following your Windows setting, with a switch in the header.
- **Remembers your work.** The last profile, folder, sample counts, window size and the components you picked for each profile come back next time.
- **Duplicate button in Manage Profiles.** Copy a built-in profile and edit the copy instead of writing regexes from scratch. File extensions are now editable per profile.
- Scan progress bar with file counts, and a clearer summary with a *Details…* report instead of pop-ups.
- Keyboard shortcuts: Ctrl+O, Ctrl+Enter / F5, Ctrl+E, Esc.

### Fixed
- Profiles you created in version 1.1.0 (kept in a `profiles.json` next to the program) are now brought over automatically the first time, so upgrading no longer leaves your own profiles behind.
- Closing the window while a scan was running left the program running invisibly until the scan finished. It now stops the scan.
- Excel section headings such as *INITIALIZE (Init)* were listed as components with empty values. They are now ignored (a profile can still keep them).
- A `{@BLOCK}` line that directly followed another block without a measurement was skipped, so its value could be missing from the export.
- Saving a profile under the name of an existing profile silently overwrote it; it now asks first.
- A damaged `profiles.json` is now backed up before being repaired, so custom profiles are no longer lost.
- Text logs saved as UTF-16 are now read correctly.
- Values such as `nan`, `inf` or `1_000` are written as text instead of being converted to numbers.
- Log text that starts with `=` can no longer turn into an Excel formula.
- A failed export no longer leaves a half-written file behind.

### Improved
- **The review table scrolls smoothly.** Scrolling the data table (and the Limits panel) used to lag because the themed table repaints every cell on every step. It is now drawn only for the rows and columns in view, so a mouse-wheel step takes about 17 ms instead of 120 to 155 ms, and clicking a row is just as quick.
- **One button style everywhere**, and the version number and credit now sit together at the bottom left of the Source card. The header keeps just the dark mode button and the Help menu.
- **Faster and lighter.** The program opens about 40% faster (it no longer loads the Excel-writing library until you export), uses about a quarter less memory, and the download is a quarter smaller. Excel logs are read several times faster, up to 7 times for workbooks with large chart sheets, such as the EOL logs.
- **The preview shows 20 columns at a time** with ‹ › buttons. Choosing hundreds of components used to freeze the window for several seconds each time the selection changed. The exported Excel file still has every column.
- **The exported Excel file is easier to read and no longer hides values.** Every column is sized to its longest value, so long decimals and scientific numbers are shown in full instead of as `####`. Long component names wrap in the heading and fit in the limits table. The heading row is dark blue with white text, the files of each sample share a background colour, numbers are right-aligned, and the sheet prints in landscape with the heading repeated on every page. The layout (which cell holds what) is unchanged.
- **The preview table fits its columns to their content**, so there is no empty space in the *File* or *Serial number* columns.
- The Jabil logo is shown in the middle of the header (a white version is used in dark mode), and the main window credits the developer at the bottom left.
- Scanning is faster on slow folders (OneDrive, network drives): several files are read in parallel.
- Excel logs are read in read-only mode, which is quicker and uses less memory.
- The window no longer freezes while exporting, and unexpected errors are logged and reported instead of disappearing.
- The application is now split into tested modules instead of one 2,400-line file.
