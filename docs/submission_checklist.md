# Submission Checklist — KĀRYO Lead Intelligence Agent

Complete every item below before submitting. Test links in an Incognito window.

---

## Documentation (Google Doc / PDF)

- [ ] Open `docs/submission_doc.md` and paste into Google Docs
- [ ] Apply heading styles (H1 for sections, H2 for subsections)
- [ ] Embed Mermaid diagram — paste `docs/architecture.md` diagram into mermaid.live, screenshot, insert image into doc
- [ ] Verify all 6 sections are present:
  - [ ] Project Title
  - [ ] Team Composition
  - [ ] Problem Statement
  - [ ] Solution Overview
  - [ ] Agent Architecture (with diagram)
  - [ ] Tech Stack
- [ ] Include sample email (from `outputs/emails/devaki_dental_clinic.txt`) in Section 7
- [ ] Include sample CSV row in Section 7
- [ ] Set sharing: **Anyone with the link can view**
- [ ] Test link in Incognito window — confirm no "Request Access" screen
- [ ] Export as PDF (optional but recommended as backup)

---

## Demo Video

- [ ] Follow `docs/video_script.md` exactly
- [ ] Pre-recording: `KARYO_CACHE_ONLY=1` set — demo runs in 5–8 seconds
- [ ] Pre-recording: font size ≥ 18pt in terminal
- [ ] Pre-recording: Do Not Disturb on, all notifications hidden
- [ ] Face-cam visible in intro (0:00–0:30) AND outro (3:30–4:00)
- [ ] No `.env` file or API keys visible at any point during screen recording
- [ ] Audio is clear — no background noise or echo
- [ ] Screen is 1080p minimum
- [ ] Video is 2–5 minutes long
- [ ] Upload to YouTube → set to **Unlisted** (NOT Private)
  - OR upload to Loom (public link by default)
- [ ] Test video link in Incognito window — confirm it plays without login
- [ ] Save the video URL

---

## GitHub Repository

- [ ] Repository is set to **Public**
- [ ] README.md includes Problem Statement, Team, Architecture, Quick Start
- [ ] No `.env` file committed (check `.gitignore`)
- [ ] All code files are present and runnable
- [ ] Test: clone the repo in a fresh directory and follow the README quick start
- [ ] Save the GitHub URL

---

## Final Submission

- [ ] Google Doc / PDF link ready and accessible
- [ ] Video link ready (YouTube Unlisted or Loom)
- [ ] GitHub repo link ready
- [ ] Test ALL links in an Incognito window right before submitting
- [ ] Submit

---

## Quick Reference — What Each Output File Is

| File | What it is |
|---|---|
| `docs/submission_doc.md` | Full competition doc — paste into Google Docs |
| `docs/architecture.md` | Mermaid diagram — render at mermaid.live |
| `docs/video_script.md` | Timestamped recording guide |
| `outputs/leads.csv` | Show in demo video (Segment 4) |
| `outputs/emails/*.txt` | Show in demo video (Segment 4) |
| `outputs/run_log.json` | Mention in demo as "full audit trail" |
| `output1.txt` / `output2.txt` | Raw terminal logs — do NOT submit these |
