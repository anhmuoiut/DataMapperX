# Changelog

Each release's notes are shown to users in the update dialog, so write them for the people who use the app.
A release cannot be published unless its version has a section here.

## [1.2.0] - 2026-10-28

### New
- **Automatic updates.** DataMapperX checks GitHub for a newer version when it starts and offers to install it with one click. The download is verified before it replaces the running program.
- **Real data preview.** The preview now shows the exact table that will be exported (values, not just file names). Samples with the wrong number of files are shown in red and missing values in amber.
- **Dark mode**, following your Windows setting, with a switch in the header.
- **Remembers your work.** The last profile, folder, sample counts, window size and the components you picked for each profile come back next time.
- **Duplicate button in Manage Profiles.** Copy a built-in profile and edit the copy instead of writing regexes from scratch. File extensions are now editable per profile.
- Scan progress bar with file counts, and a clearer summary with a *Details…* report instead of pop-ups.
- Keyboard shortcuts: Ctrl+O, Ctrl+Enter / F5, Ctrl+E, Esc.

### Fixed
- A `{@BLOCK}` line that directly followed another block without a measurement was skipped, so its value could be missing from the export.
- Saving a profile under the name of an existing profile silently overwrote it; it now asks first.
- A damaged `profiles.json` is now backed up before being repaired, so custom profiles are no longer lost.
- Text logs saved as UTF-16 are now read correctly.
- Values such as `nan`, `inf` or `1_000` are written as text instead of being converted to numbers.
- Log text that starts with `=` can no longer turn into an Excel formula.
- A failed export no longer leaves a half-written file behind.

### Improved
- Scanning is faster on slow folders (OneDrive, network drives): several files are read in parallel.
- Excel logs are read in read-only mode, which is quicker and uses less memory.
- The window no longer freezes while exporting, and unexpected errors are logged and reported instead of disappearing.
- The application is now split into tested modules instead of one 2,400-line file.
