# Templates Directory

This directory is reserved for character template images that can be used for template matching as an alternative to OCR.

## Future Enhancement

Instead of using Tesseract OCR, you can:

1. Capture reference images of each character from the MCDU
2. Store them as templates in this directory
3. Use OpenCV template matching for faster character recognition

## Template Format

Templates should be:
- PNG format
- Grayscale or RGB
- Same size (e.g., 20x20 pixels)
- Named by character (e.g., `A.png`, `B.png`, `0.png`, etc.)

## Example Structure

```
templates/
├── characters/
│   ├── A.png
│   ├── B.png
│   ├── C.png
│   └── ...
├── symbols/
│   ├── degree.png
│   ├── arrow_left.png
│   └── ...
└── numbers/
    ├── 0.png
    ├── 1.png
    └── ...
```

## Using Templates

To use template matching instead of OCR, modify `mcdu_parser.py`:

```python
import cv2

class MCDUParser:
    def __init__(self, image, templates_dir='templates/characters'):
        self.image = image
        self.templates = self._load_templates(templates_dir)
    
    def _load_templates(self, templates_dir):
        templates = {}
        for template_file in Path(templates_dir).glob('*.png'):
            char = template_file.stem
            template = cv2.imread(str(template_file), cv2.IMREAD_GRAYSCALE)
            templates[char] = template
        return templates
    
    def detect_character(self, cell):
        # Convert cell to grayscale
        gray = cv2.cvtColor(cell, cv2.COLOR_RGB2GRAY)
        
        best_match = None
        best_score = 0
        
        # Try each template
        for char, template in self.templates.items():
            result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            
            if max_val > best_score:
                best_score = max_val
                best_match = char
        
        return best_match if best_score > 0.7 else None
```

This approach is typically faster and more accurate than OCR for fixed fonts.
