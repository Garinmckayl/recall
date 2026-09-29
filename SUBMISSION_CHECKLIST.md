# Devpost submission checklist — Recall

Deadline: **Oct 23, 2026, 12:00 pm PT** (AWS credit request form due Oct 21, 12 pm PT). Submit a day early.

## Already done (in this repository)
- [x] Public repo with an open-source license (MIT) — https://github.com/Garinmckayl/recall
- [x] Runs from a clean clone; 34 offline tests pass (`python3 -m pytest tests -q`)
- [x] Repo calls Ring technology at runtime (`ring_api.py`, `/ring/webhook`, `pipeline.sync`) and the video shows it on the Ring sandbox
- [x] Text description → `SUBMISSION.md`
- [x] Product feedback for every tool/API → `PRODUCT_FEEDBACK.md` (+ friction log `FRICTION_LOG.md`, worth up to a 10% bonus)
- [x] New-vs-existing explanation → `SUBMISSION.md` ("What was built during the submission period")
- [x] Open Source mini challenge details (contribution URL, repo URL, username, description) → `SUBMISSION.md`
- [x] AWS Builder documented integrations → `SUBMISSION.md` + `PRODUCT_FEEDBACK.md`
- [x] 2:56 demo video, 1080p, English, labelled sandbox/dramatization, generated (licensed) music
- [x] Thumbnail (3:2) and 8 gallery images → `docs/devpost/`
- [x] Upload text for the video → `docs/devpost/YOUTUBE_UPLOAD.md`

## You need to do
1. [ ] **Upload the video** (public) to YouTube or Vimeo using `docs/devpost/YOUTUBE_UPLOAD.md`; copy the URL.
2. [ ] **Deploy the live demo** so judges can test without setup: `cp deploy/host.env.example deploy/host.env` (already filled in locally), then `bash deploy/go.sh`. Copy the HTTPS link it prints. Devpost requires the project to be free and unrestricted for testing through the end of judging (Nov 9–20) — keep the host running, and re-run `deploy/go.sh` if the tunnel URL changes (or give the host a domain; see the README).
3. [ ] In `SUBMISSION.md`, replace `[[VIDEO URL]]` and `[[LIVE DEMO URL]]` (there are three places), then add "Amazon EC2" to *Built with* and a short EC2 note to `PRODUCT_FEEDBACK.md` once the deploy is live.
4. [ ] On Devpost: create the project, paste each section of `SUBMISSION.md`, add the thumbnail and gallery images, add the video URL, select tracks/mini challenges (Ring, AWS Builder, Open Source), and add the repo URL.
5. [ ] Product feedback field: paste or link `PRODUCT_FEEDBACK.md`; attach the friction log for the bonus.
6. [ ] Request the AWS credits (form due Oct 21) if you want them.
7. [ ] Confirm your ElevenLabs plan allows commercial use of the generated music/voice, and that the shared-library voice (Brian, `gPPH6SLdL8XSX6GNJ40G`) is permitted for your use — the video may be promoted by Amazon/Devpost.
8. [ ] Optional: contribute back — send the Ring team the sandbox/webhook feedback in `PRODUCT_FEEDBACK.md`.
9. [ ] Submit early; edits are not allowed after the deadline.
