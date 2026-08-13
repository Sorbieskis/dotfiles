---
name: photos
description: Pick up photos the founder just dropped from their phone via photo-drop (~/drop) and act on them. Use when they say they uploaded/dropped/sent a picture or screenshot, or invoke /photos directly. Reads the batch note first — the note is usually the actual instruction — then the images, then does the work it asks for.
---

# Pick up dropped photos

A terminal session can't take an attachment, so the founder sends images through
**photo-drop** (`http://100.93.13.127:8123`, tailnet-only, `photo-drop.service`).
One pick = one numbered batch in `~/drop/<n>/`, with an optional note typed on the
phone keyboard.

```
~/drop/0007/note.md        what they typed — often the real instruction
~/drop/0007/1-IMG_x.jpg    shots, numbered in the order they picked them
~/drop/latest              symlink -> newest batch
```

## Argument

- **none** → the newest batch (`~/drop/latest`)
- **a number** (`/photos 7`) → that batch; pad to 4 digits (`7` → `0007`)
- **`list`** → inventory only: batch numbers, shot counts, notes. Read no images.

## Steps

1. **Resolve the batch.** No arg → `~/drop/latest`. Number → `~/drop/<padded>`.
   If it doesn't exist, list what does (`ls ~/drop/`) and stop — don't guess at a
   neighbouring batch.

2. **Read `note.md` FIRST, before any image.** It is usually not a caption but the
   task ("save button does nothing on mobile", "transcribe this plate"). It tells
   you what the images are *for*, which changes what you look for in them. If
   there's no note, the images have to speak for themselves — say so rather than
   inventing an interpretation.

3. **Read the shots**, in order, by their numeric prefix so "the third one" in the
   note resolves to `3-*`. Say which numbered shot each observation comes from.

   **Watch the context cost — a phone photo is ~4000×3000 and expensive.** Up to
   ~5 shots: read them all. More than that: read the note, list the filenames,
   read the first two or three, then ask which of the rest matter rather than
   pulling in twenty. A batch can hold any number (30 verified); the limit is your
   context, not the tool.

4. **Do the work the note asks for.** This is the point of the skill — the founder
   dropped the photos to get something done, not to have them described. If it's a
   UI bug, go find the code and fix it. If it's a document or a rating plate,
   transcribe it. Describe the image only when describing *is* the request, or when
   you need to confirm you're looking at the right thing before acting.

5. **Leave the files alone.** Don't delete or move a batch after reading it — they
   are the founder's, and numbering is designed so an old batch stays referenceable
   (`~/drop/index.tsv` is append-only, so numbers are never recycled). Only clean up
   when explicitly asked.

## If nothing is there

- `~/drop/` empty or only `latest` → say so and give the URL. Don't hunt elsewhere.
- Newly-dropped photos missing → check the service is up:
  `systemctl --user is-active photo-drop` and `journalctl --user -u photo-drop -n 20`.
  It binds the Tailscale IP, so it also fails if the tailnet is down. Restart with
  `systemctl --user restart photo-drop`.
