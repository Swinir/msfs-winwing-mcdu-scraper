#!/usr/bin/env python3
"""
Example/Demo script for MSFS A330 WinWing MCDU Scraper

This script demonstrates the basic functionality without requiring
actual MSFS or WinWing hardware.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

def demo_config():
    """Demonstrate configuration loading"""
    print("\n" + "="*60)
    print("1. Configuration Demo")
    print("="*60)
    
    from config import Config
    
    print("\nGrid Specifications:")
    print(f"  Columns: {Config.CDU_COLUMNS}")
    print(f"  Rows: {Config.CDU_ROWS}")
    print(f"  Total Cells: {Config.CDU_CELLS}")
    
    print("\nFont Sizes:")
    print(f"  Large: {Config.FONT_SIZE_LARGE}")
    print(f"  Small: {Config.FONT_SIZE_SMALL}")
    
    print("\nColor Codes:")
    for code, name in Config.COLORS.items():
        print(f"  '{code}': {name}")
    
    print("\nSpecial Characters:")
    for char, unicode_val in Config.SPECIAL_CHARS.items():
        print(f"  '{char}': {unicode_val}")

def demo_parser():
    """Demonstrate MCDU parser"""
    print("\n" + "="*60)
    print("2. MCDU Parser Demo")
    print("="*60)
    
    try:
        import numpy as np
        from mcdu_parser import MCDUParser
        
        # Create a test image (480x280 pixels)
        test_image = np.zeros((280, 480, 3), dtype=np.uint8)
        
        print("\nCreating parser for 480x280 test image...")
        parser = MCDUParser(test_image)
        
        print(f"  Cell Width: {parser.cell_width}px")
        print(f"  Cell Height: {parser.cell_height}px")
        print(f"  Grid: {parser.rows} rows x {parser.columns} columns")
        
        print("\nFont size determination:")
        for row in range(14):
            size_name = "Small" if parser.is_small_font(row) else "Large"
            print(f"  Row {row:2d}: {size_name}")
        
        print("\nColor detection test:")
        # Create test cells with different colors
        white_cell = np.ones((20, 20, 3), dtype=np.uint8) * 255
        cyan_cell = np.zeros((20, 20, 3), dtype=np.uint8)
        cyan_cell[:, :, 1:3] = 200
        
        print(f"  White cell: '{parser.detect_color(white_cell)}'")
        print(f"  Cyan cell: '{parser.detect_color(cyan_cell)}'")
        
        print("\nParsing empty grid...")
        result = parser.parse_grid()
        print(f"  Total cells parsed: {len(result)}")
        print(f"  Empty cells: {sum(1 for cell in result if cell == [])}")
        
    except ImportError as e:
        print(f"\n  Skipped: Missing dependencies ({e})")

def demo_message_format():
    """Demonstrate WebSocket message format"""
    print("\n" + "="*60)
    print("3. WebSocket Message Format Demo")
    print("="*60)
    
    import json
    
    print("\nExample message to WinWing CDU:")
    
    # Create example data
    example_data = []
    
    # Row 0 (Title - Large font)
    title = "MCDU TEST"
    for i, char in enumerate(title):
        example_data.append([char, "w", 0])  # White, large
    for _ in range(24 - len(title)):
        example_data.append([])
    
    # Row 1 (Label - Small font)
    for _ in range(24):
        example_data.append([])
    
    # Remaining rows (288 cells = 12 rows * 24 columns)
    for _ in range(288):
        example_data.append([])
    
    message = {
        "Target": "Display",
        "Data": example_data
    }
    
    json_str = json.dumps(message, indent=2)
    
    # Show first part of message
    lines = json_str.split('\n')
    print('\n'.join(lines[:20]))
    print("    ... (truncated)")
    print(f"\n  Total data elements: {len(example_data)}")
    print(f"  Non-empty cells: {sum(1 for cell in example_data if cell != [])}")

def demo_screen_capture():
    """Demonstrate screen capture (without actual capture)"""
    print("\n" + "="*60)
    print("4. Screen Capture Demo")
    print("="*60)
    
    print("\nScreen capture configuration:")
    region = {
        "top": 400,
        "left": 800,
        "width": 480,
        "height": 280
    }
    
    for key, value in region.items():
        print(f"  {key}: {value}")
    
    print("\nCapture process:")
    print("  1. Initialize MSS with monitor region")
    print("  2. Grab screenshot from specified region")
    print("  3. Convert to numpy array (RGB)")
    print("  4. Pass to MCDU parser")
    
    try:
        from screen_capture import ScreenCapture
        print("\n  ✓ ScreenCapture module loaded successfully")
        print("  (Actual capture requires MSS and running MSFS)")
    except ImportError as e:
        print(f"\n  Note: Missing dependencies ({e})")

def main():
    """Main demo function"""
    print("="*60)
    print("MSFS A330 WinWing MCDU Scraper - Demo")
    print("="*60)
    print("\nThis demo shows the basic components without requiring")
    print("actual MSFS or WinWing hardware.")
    
    demo_config()
    demo_parser()
    demo_message_format()
    demo_screen_capture()
    
    print("\n" + "="*60)
    print("Demo Complete!")
    print("="*60)
    print("\nTo run the actual scraper:")
    print("  1. Configure config.yaml with your screen coordinates")
    print("  2. Start MSFS with Airbus A330")
    print("  3. Start MobiFlight WinWing MCDU Connector")
    print("  4. Run: cd src && python main.py")
    print()

if __name__ == '__main__':
    main()
