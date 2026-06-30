# FS42 Portable Launcher: Plain-English Guide

This is the everyday guide for running FieldStation42 as a portable TV station.

The goal is simple:

1. Keep the real media in MEGA.
2. Keep this project folder portable.
3. Use local symlinks so FS42 can see the media.
4. Scan the media once on one computer.
5. Upload the finished scan and schedules.
6. Let every other computer download that finished work instead of scanning again.

## The Pieces

### `confs/`

This folder contains one JSON config file per channel.

Example:

```bash
confs/actionmax.json
confs/classicmovies.json
confs/comedyhub.json
```

These files tell FS42 what channels exist and where each channel's local media folder is.

### `catalog/`

This folder contains local symlinks to the MEGA media.

Example:

```bash
catalog/actionmax/actionmax -> ~/mega/FS42_MEDIA/Channels/ActionMax/ActionMax
catalog/actionmax/bump -> ~/mega/FS42_MEDIA/Channels/ActionMax/bump
catalog/actionmax/commercial -> ~/mega/FS42_MEDIA/Channels/ActionMax/commercial
```

FS42 reads from `catalog/`, but the actual files still live in MEGA.

Do not hand-edit these symlinks unless you are fixing something specific. Use the commands below.

### `runtime/catalogs/`

This is where the scanner saves the media catalog files.

These files are the expensive part. A big scan can take a long time.

Example:

```bash
runtime/catalogs/actionmax.pkl
runtime/catalogs/classicmovies.pkl
```

### `runtime/schedules/`

This is where FS42 saves compiled schedules.

Example:

```bash
runtime/schedules/actionmax.pkl
runtime/schedules/classicmovies.pkl
```

### `runtime/fs42_fluid.db`

This is the local FS42 database/cache.

It is also part of the compiled runtime state.

### MEGA compiled backup

The finished scanner and schedule output can be uploaded to:

```bash
mega:FS42_MEDIA/Compiled
```

That remote folder is what lets other machines skip the long scan.

## Normal Commands

### Start the web console

```bash
env/bin/python station_42.py
```

Then open:

```text
http://localhost:4242
```

Use this when you want the new browser interface for managing stations, catalogs, schedules, and the FS42 API.

If you want to run the web server after another command, use:

```bash
env/bin/python station_42.py --server
```

### Launch FS42 in a window

```bash
./launch.sh --windowed
```

Use this while developing on a desktop.

### Launch FS42 fullscreen

```bash
./launch.sh --fullscreen
```

Fullscreen is the normal TV mode.

### Check the whole setup

```bash
./launch.sh --doctor
```

This checks config, rclone, MEGA, schedules, media, permissions, and the runtime folders.

Use this when you copy the project to a new computer or something feels wrong.

### Validate channels

```bash
./launch.sh --validate
```

This checks every channel and tells you what is missing.

Common errors:

```text
Missing catalog file
Missing schedule file
Missing media file
Missing bumper folder
Missing commercial folder
```

If the media symlinks exist but the scanner has not run yet, validation will complain about missing files in `runtime/catalogs/` and `runtime/schedules/`. That is normal before scanning.

### Find channels in MEGA and create local symlinks

```bash
./launch.sh --discover-media-channels
```

This scans:

```bash
~/mega/FS42_MEDIA/Channels
```

It creates:

```bash
confs/<channel>.json
catalog/<channel>/...
```

Use this when you add new channel folders in MEGA.

### Refresh existing symlinks

```bash
./launch.sh --sync-media-links
```

This updates the local `catalog/` symlinks from the existing channel config files.

Use this after copying the project to another machine, or after the MEGA mount point changes.

## Scanning Media

The scanner is what turns the media folders into FS42 runtime cache files.

### Scan all channels

```bash
env/bin/python station_42.py --rebuild_catalog
```

This can take a long time.

You usually only want to do this on one main computer.

### Scan one channel

```bash
env/bin/python station_42.py --rebuild_catalog actionmax
```

Use this when you only changed one channel.

Replace `actionmax` with the channel name you want to scan.

### Build schedules for all channels

```bash
env/bin/python station_42.py --add_day
```

Run this after scanning.

### Build a schedule for one channel

```bash
env/bin/python station_42.py --add_day actionmax
```

Use this after scanning one channel.

## Backing Up The Scan

After scanning and building schedules, upload the finished runtime files to MEGA.

```bash
./launch.sh --upload-compiled
```

This uploads:

```bash
runtime/catalogs/*.pkl
runtime/schedules/*.pkl
runtime/fs42_fluid.db
runtime/compiled_manifest.json
```

To:

```bash
mega:FS42_MEDIA/Compiled
```

This is the command that makes the long scan reusable on other computers.

It will refuse to upload if the scanner has not created catalog files yet, or if schedules have not been built yet.

## Downloading The Scan On Another Computer

On another machine, download the finished compiled cache:

```bash
./launch.sh --sync-compiled
```

This pulls the latest uploaded catalogs, schedules, database, and manifest from MEGA.

After that, the machine should not need to run the slow full scanner.

## Checking Compiled Cache Status

```bash
./launch.sh --compiled-status
```

This shows whether you have local compiled files and whether MEGA has a compiled backup.

It also shows how many local catalog and schedule files exist.

Use this when you are not sure if the cache has been uploaded yet.

## Force Download The Compiled Cache

```bash
./launch.sh --force-sync-compiled
```

This replaces the local compiled cache with the MEGA version.

Only use this when you are sure the MEGA version is the one you want.

## Normal Workflow: Main Scanner Computer

Use this workflow on the computer that does the heavy scan.

### 1. Check the setup

```bash
./launch.sh --doctor
```

Fix anything important it reports.

### 2. Discover channels from MEGA

```bash
./launch.sh --discover-media-channels
```

This creates channel config files and local media symlinks.

### 3. Scan the media

```bash
env/bin/python station_42.py --rebuild_catalog
```

This is the slow step.

Let it finish.

### 4. Build schedules

```bash
env/bin/python station_42.py --add_day
```

This creates the runtime schedules FS42 plays from.

### 5. Validate the channels

```bash
./launch.sh --validate
```

The important missing catalog and schedule errors should be gone after scanning and scheduling.

### 6. Upload the compiled cache

```bash
./launch.sh --upload-compiled
```

This saves the scan and schedules to MEGA so other machines can use them.

### 7. Launch FS42

```bash
./launch.sh --windowed
```

Or, for TV mode:

```bash
./launch.sh --fullscreen
```

## Normal Workflow: Other Computers

Use this workflow on a Raspberry Pi, another Linux PC, or any copied FS42 folder.

### 1. Copy the project folder

Copy the whole `FieldStation42-Pi` folder to the new machine.

### 2. Make sure MEGA is mounted

```bash
./launch.sh --doctor
```

If rclone or the MEGA remote is missing, the doctor command will tell you.

### 3. Recreate local symlinks

```bash
./launch.sh --sync-media-links
```

This makes `catalog/` point at the MEGA media on that computer.

### 4. Download the compiled cache

```bash
./launch.sh --sync-compiled
```

This downloads the scanner output and schedules from MEGA.

### 5. Validate

```bash
./launch.sh --validate
```

If this looks good, the machine is ready.

### 6. Launch

```bash
./launch.sh --windowed
```

Or:

```bash
./launch.sh --fullscreen
```

## When You Add More Media

### If you add files inside an existing channel

Example:

```bash
~/mega/FS42_MEDIA/Channels/ActionMax/ActionMax/new_movie.mp4
```

Run this on the main scanner computer:

```bash
env/bin/python station_42.py --rebuild_catalog actionmax
env/bin/python station_42.py --add_day actionmax
./launch.sh --upload-compiled
```

Then other computers can run:

```bash
./launch.sh --sync-compiled
```

### If you add a brand-new channel folder

Run this on the main scanner computer:

```bash
./launch.sh --discover-media-channels
env/bin/python station_42.py --rebuild_catalog
env/bin/python station_42.py --add_day
./launch.sh --upload-compiled
```

Then other computers can run:

```bash
./launch.sh --sync-media-links
./launch.sh --sync-compiled
```

## What Happens Automatically On Launch

When you run:

```bash
./launch.sh --windowed
```

or:

```bash
./launch.sh --fullscreen
```

the launcher tries to help:

1. It loads the config.
2. It checks the MEGA mount if configured.
3. It refreshes media symlinks if auto-sync is enabled.
4. It safely checks for compiled schedules on MEGA.
5. It validates channels.
6. It starts the player.

The compiled sync is careful by default. If you already have local compiled files but no local manifest, it will not overwrite them unless you use:

```bash
./launch.sh --force-sync-compiled
```

## Commands To Avoid Misusing

### Do not full-scan every computer

This is slow:

```bash
env/bin/python station_42.py --rebuild_catalog
```

Only the main scanner computer should usually do the full scan.

Other computers should use:

```bash
./launch.sh --sync-compiled
```

### Do not force-sync unless you mean it

This replaces local compiled files:

```bash
./launch.sh --force-sync-compiled
```

Use normal sync first:

```bash
./launch.sh --sync-compiled
```

### Do not edit generated symlinks by hand

Use:

```bash
./launch.sh --sync-media-links
```

or:

```bash
./launch.sh --discover-media-channels
```

## Current Project State

Right now this project has:

```text
37 channel config files
129 local media symlinks
```

The old broken channels were removed:

```text
Anime Retro
Dark World
```

The generated channel configs now use clean names like:

```bash
confs/actionmax.json
confs/classicmovies.json
confs/comedyhub.json
```

They no longer use names like:

```bash
confs/generated_actionmax.json
```

The local media folders live directly under:

```bash
catalog/<channel>/
```

They no longer live under:

```bash
catalog/generated/
```

Before the scanner finishes, validation may still report missing catalog and schedule files. That is expected.

After scanning and scheduling, run:

```bash
./launch.sh --upload-compiled
```

That is the step that backs up the scan so other machines do not have to repeat it.
