# Test Suite

This directory contains unit tests for the MSFS WinWing MCDU Scraper.

## Test Files

- **test_parser.py** - Tests for MCDU parser and character detection
- **test_region_selector.py** - Tests for region selector coordinate transformations and window capture crop validation

## Running Tests

### Run All Tests (Minimal Dependencies)

To run tests without GUI dependencies (region selector tests only):

```bash
# Install minimal dependencies
pip install numpy

# Run region selector tests
python -m unittest tests.test_region_selector -v
```

### Run All Tests (Full Dependencies)

To run all tests including parser tests:

```bash
# Install full test dependencies
pip install -r requirements.txt

# Run all tests
python -m unittest discover -s tests -v
```

### Run Specific Test File

```bash
# Run only region selector tests
python -m unittest tests.test_region_selector -v

# Run only parser tests
python -m unittest tests.test_parser -v
```

### Run Specific Test Class

```bash
# Run only coordinate transformation tests
python -m unittest tests.test_region_selector.TestRegionSelectorCoordinates -v

# Run only crop validation tests
python -m unittest tests.test_region_selector.TestWindowCaptureCropValidation -v
```

### Run Specific Test Method

```bash
# Run a single test
python -m unittest tests.test_region_selector.TestRegionSelectorCoordinates.test_coordinate_transformation_with_scaling -v
```

## Test Coverage

### RegionSelectorDialog Tests (test_region_selector.py)

**TestRegionSelectorCoordinates** (6 tests):
- ✅ Coordinate transformation without scaling
- ✅ Coordinate transformation with scaling
- ✅ Asymmetric scaling (different x/y ratios)
- ✅ Width/height calculation
- ✅ Minimum selection size enforcement
- ✅ Rectangle normalization (inverted coordinates)

**TestWindowCaptureCropValidation** (7 tests):
- ✅ Crop region within bounds
- ✅ Crop region exceeding bounds
- ✅ Crop region completely outside bounds
- ✅ Detection of significantly reduced crops
- ✅ Coordinate clamping
- ✅ Crop region format validation
- ✅ Image slicing with crop

**TestEdgeCases** (5 tests):
- ✅ Zero-width crop handling
- ✅ Zero-height crop handling
- ✅ Single-pixel crop
- ✅ Maximum size crop
- ✅ Aspect ratio preservation

### Parser Tests (test_parser.py)

**TestMCDUParser** (8 tests):
- ✅ Parser initialization
- ✅ Cell extraction
- ✅ Color detection (white, cyan, green)
- ✅ Empty cell detection
- ✅ Font size determination
- ✅ Grid parsing

**TestConfig** (3 tests):
- ✅ Configuration constants
- ✅ Font sizes
- ✅ Color codes

## Test Statistics

- **Total Tests**: 29
- **Test Files**: 2
- **Test Classes**: 5
- **Lines of Test Code**: ~450

## CI/CD Integration

These tests are designed to run in CI/CD environments without requiring:
- GUI components (tkinter)
- Windows-specific APIs (pywin32)
- Heavy dependencies (when running minimal test suite)

The `test_region_selector.py` tests validate logic without importing GUI code, making them suitable for headless CI environments.
