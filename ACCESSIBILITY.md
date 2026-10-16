# Accessibility

STARK OS should be usable by everyone, and it helps your audience too: E.D.I.T.H. and U write alt text and captions, and the rule check warns about images without alt text.

## What the dashboard supports

- Full keyboard use: visible focus outline, labelled buttons and form fields, and push-to-talk with Space or Enter.
- Screen readers: labelled controls, `aria-pressed` / `aria-expanded` / `aria-current` states, and errors announced as alerts.
- Text contrast checked against WCAG AA for normal and small text.
- Works on phones (no sideways scrolling down to 360 px wide, tested automatically).
- Reduced motion: status animations stop when your system asks for reduced motion.
- Voice is optional; everything also works with text.

## Known gaps

- The collaboration graph is visual; the same information is listed as text below it.
- Speech recognition depends on your browser (Chrome, Edge and Safari support it).

## Report a barrier

Open an [issue](https://github.com/Shahrukhalid/stark-os/issues/new/choose) and choose **Bug report** with area "Dashboard". Describe what you were trying to do and which assistive technology you use. Accessibility bugs are treated as high priority.
