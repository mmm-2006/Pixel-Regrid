# k-centroid

`pixel_k_centroid.py` adapts the local color clustering and dominant-color
resizing approach from Astropulse's `pixeldetector/k-centroid.py`:
https://github.com/Astropulse/pixeldetector/blob/6e88e18ddbd16529b5dd85b1c615cbb2e5778bf2/k-centroid.py

Adaptations include fractional area weighting, transparency support, cancellation,
deterministic color tie handling, and nearest-neighbor enlargement. Results are
not guaranteed to match the original script or PixelOE's Torch implementation.

MIT License

Copyright (c) 2023 Astropulse

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
