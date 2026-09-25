# Section stepping

In QA / cross-sections, choose a Section source and pick A then B in the
3D Top view. Set Full width and Step distance (both in the cloud's map units).
Click Step left or Step right. Looking from A toward B, left is the left-hand
perpendicular direction. Both endpoints move together; length, orientation
and width stay unchanged. Reversing A/B reverses what left/right mean.

Each click automatically extracts the shifted corridor, using the existing
cache policy and source selection. Stop cancels extraction. The moved corridor
remains in place after cancellation/failure; Extract section retries it, or
step the opposite way to return. Empty corridors show an empty profile.
Buttons are disabled during work; clicks do not queue extra scans.

The distance defaults to 10 map units and is session-local. Existing color,
line filter and vertical exaggeration remain selected; the new profile fits
its extracted data. Sources and classifications are unchanged. This is manual
parallel-section stepping, not automatic following of a curved road alignment.
Saved review presets and section-navigation persistence remain future work.
