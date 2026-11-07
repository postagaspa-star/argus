# Argus

A study-time keeper I built for myself: two cameras at home, a small server on a home NAS and a
program on my Windows laptop. On school days there is a **quota** of real work (one hour by default).
Until it is done, the laptop only runs what is on the study list. When it is done, everything is free
again.

It is not a parental control and nobody else runs it on me. I wanted something that notices when I sit
on the sofa "for five minutes" and an hour goes by, and that can tell studying from scrolling better
than a timer I start and forget.

## How it works

- **The cameras** (cheap pan-tilt Tapo models) are read by the NAS a frame or two per second. Small
  open models find people and objects, the pose, the face (so it follows me and not my family), and
  recognise my school books, notebooks and phone from photos I register once. Frames are never stored.
- **A diary in words** is written every ten seconds ("15:40 at the desk, history book open, laptop on
  Wikipedia"). Clear cases are decided by plain rules. Cases that need judgement ("was that staring at
  the ceiling studying?") go to a local decision model that only picks between fixed answers
  ([SemIf](https://github.com/TheoLeeCJ/SemIf-OpenJev) with Qwen3.5-4B, shared with another project on
  the same NAS). When a picture really has to be looked at, the laptop runs Qwen3.5-9B on its CPU, only
  while it is plugged in and has memory to spare.
- **The laptop program** watches the foreground app and the site in the address bar, and covers the
  screen when something outside the lists is in front. A hidden terminal (Ctrl+Alt+T) takes short
  commands: `ps` for a break with a reason and a length, `lv` for work time, `dm` for a nap, `st` for
  the state, plus commands to register books, notebooks, my face and my phone.

## The rules that matter

- **A quota, not a punishment clock.** Getting distracted doesn't lock things for hours: each lost
  minute counts double against the quota, with a daily cap. The only way out is to do the work.
- **When in doubt, nothing happens.** A penalty needs clear evidence. Unclear moments neither count as
  study nor add to the quota.
- **Things you can't block get consequences instead.** Another phone or a tablet can't be locked by
  this system, so using one adds thirty minutes; a TV or console on a smart plug gets switched off.
- **Loosening is slow, tightening is instant.** Adding something to an allowed list takes effect after
  four days; removing it takes effect at once.
- **If the server goes quiet, the laptop gets stricter, not looser.** An emergency unlock exists, but it
  needs the administrator password, which isn't mine.

The full rules are in [`docs/regole.md`](docs/regole.md) and the protocol between the pieces in
[`docs/contratto.md`](docs/contratto.md) (both in Italian, like the domain terms in the code).

## Status

Built and tested on the bench, **not yet in real use**: the cameras haven't been bought yet. Without
cameras configured the server stays inactive and doesn't count, penalise or cover anything. What has
been run for real: the vision models on sample photos, the laptop's model engine with a small model of
the same family, the laptop protocol against the real server on the NAS, the decision model and the
voice service from inside the server's container. What still needs the real house: camera
streams and pan-tilt control, the camera speaker, threshold tuning on real images, the Windows service
under a real install.

## Stack

- `nas/`: Python 3.12, FastAPI, ONNX Runtime/OpenVINO, MediaPipe, OpenCV, SQLite, Docker; go2rtc for
  the camera streams and speaker. Models: D-FINE S (objects), SigLIP 2 (books and phone), YuNet + SFace
  (face), MediaPipe (pose). All Apache-2.0 or MIT.
- `pc/`: C# on .NET 8, WinForms + WebView2, a Windows service that restarts the agent if it's closed,
  llama.cpp's server for the vision model.

I make the product and rule decisions; Claude writes the implementation.

Personal project, not a product, and not advice on how anyone else should study.
