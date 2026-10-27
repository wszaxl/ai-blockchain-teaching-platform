# -*- coding: utf-8 -*-
"""Extract thumbnail contact sheets from the operation recordings so we can
locate timestamps showing the Ant Chain console / explorer pages."""
import os
import sys
import cv2
from PIL import Image, ImageDraw

VIDEO = sys.argv[1]
STEP = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
OUT = sys.argv[3] if len(sys.argv) > 3 else "/tmp/sheets"
os.makedirs(OUT, exist_ok=True)

cap = cv2.VideoCapture(VIDEO)
fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
dur = total / fps
print("fps=%.2f frames=%d duration=%.1fs" % (fps, total, dur))

thumbs = []
t = 0.0
while t < dur:
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    if not ok:
        break
    h, w = frame.shape[:2]
    tw = 320
    th = int(h * tw / w)
    small = cv2.resize(frame, (tw, th))
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 70, 16], fill=(0, 0, 0))
    d.text((4, 2), "%.0fs" % t, fill=(255, 255, 0))
    thumbs.append(img)
    t += STEP
cap.release()
print("thumbs:", len(thumbs))

PER = 24
COLS = 6
for s in range(0, len(thumbs), PER):
    chunk = thumbs[s:s + PER]
    rows = (len(chunk) + COLS - 1) // COLS
    tw, th = chunk[0].size
    sheet = Image.new("RGB", (COLS * tw, rows * th), (20, 20, 20))
    for i, im in enumerate(chunk):
        sheet.paste(im, ((i % COLS) * tw, (i // COLS) * th))
    name = os.path.join(OUT, "sheet_%02d.png" % (s // PER))
    sheet.save(name)
    print("saved", name)
