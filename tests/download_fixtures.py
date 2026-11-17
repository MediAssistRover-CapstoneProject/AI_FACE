"""Public-domain NASA portraits distributed with scikit-image/matplotlib.

Sources and provenance:
https://scikit-image.org/docs/stable/api/skimage.data.html#skimage.data.astronaut
https://matplotlib.org/stable/gallery/images_contours_and_fields/image_demo.html
Fixtures are for model smoke tests, not a representative evaluation dataset.
"""
import urllib.request
from pathlib import Path

root = Path(__file__).parent / 'fixtures'
root.mkdir(exist_ok=True)
sources = {
    'astronaut.png': 'https://raw.githubusercontent.com/scikit-image/scikit-image/v0.24.0/skimage/data/astronaut.png',
    'grace_hopper.jpg': 'https://raw.githubusercontent.com/matplotlib/matplotlib/v3.9.2/lib/matplotlib/mpl-data/sample_data/grace_hopper.jpg',
}
for name, url in sources.items():
    (root / name).write_bytes(urllib.request.urlopen(url, timeout=30).read())
