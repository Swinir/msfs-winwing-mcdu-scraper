#!/usr/bin/env python3
"""
Validation script to check code structure and imports without running full application
"""

import sys
import ast
from pathlib import Path

def validate_python_file(filepath):
    """Validate Python file syntax"""
    print(f"Validating {filepath}...")
    try:
        with open(filepath, 'r') as f:
            code = f.read()
        ast.parse(code)
        print(f"  ✓ {filepath} - Syntax OK")
        return True
    except SyntaxError as e:
        print(f"  ✗ {filepath} - Syntax Error: {e}")
        return False

def check_imports(filepath):
    """Check that imports are structured correctly"""
    print(f"Checking imports in {filepath}...")
    try:
        with open(filepath, 'r') as f:
            code = f.read()
        tree = ast.parse(code)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        print(f"  Imports: {', '.join(imports) if imports else 'None'}")
        return True
    except Exception as e:
        print(f"  ✗ Error checking imports: {e}")
        return False

def main():
    """Main validation"""
    print("="*60)
    print("MSFS WinWing MCDU Scraper - Code Validation")
    print("="*60)
    
    src_path = Path(__file__).parent / 'src'
    
    files_to_validate = [
        src_path / '__init__.py',
        src_path / 'config.py',
        src_path / 'screen_capture.py',
        src_path / 'mcdu_parser.py',
        src_path / 'mobiflight_client.py',
        src_path / 'main.py',
        src_path / 'window_capture.py',
        src_path / 'gui.py',
        src_path / 'region_selector.py',
    ]
    
    all_valid = True
    
    print("\n1. Syntax Validation")
    print("-" * 60)
    for filepath in files_to_validate:
        if not validate_python_file(filepath):
            all_valid = False
    
    print("\n2. Import Structure Check")
    print("-" * 60)
    for filepath in files_to_validate:
        if filepath.name != '__init__.py':
            check_imports(filepath)
    
    print("\n3. Project Structure Check")
    print("-" * 60)
    
    required_files = [
        'README.md',
        'requirements.txt',
        'config.yaml.example',
        '.gitignore',
        'src/__init__.py',
        'src/config.py',
        'src/screen_capture.py',
        'src/mcdu_parser.py',
        'src/mobiflight_client.py',
        'src/main.py',
        'docs/SETUP.md',
        'docs/CALIBRATION.md',
        'tests/__init__.py',
        'tests/test_parser.py',
    ]
    
    project_root = Path(__file__).parent
    
    for file_path in required_files:
        full_path = project_root / file_path
        if full_path.exists():
            print(f"  ✓ {file_path}")
        else:
            print(f"  ✗ {file_path} - MISSING")
            all_valid = False
    
    print("\n4. Configuration Check")
    print("-" * 60)
    
    # Check config.yaml.example
    config_example = project_root / 'config.yaml.example'
    if config_example.exists():
        print(f"  ✓ config.yaml.example exists")
        import yaml
        try:
            with open(config_example) as f:
                config_data = yaml.safe_load(f)
            
            required_sections = ['mcdu', 'mobiflight', 'performance']
            for section in required_sections:
                if section in config_data:
                    print(f"  ✓ Section '{section}' present")
                else:
                    print(f"  ✗ Section '{section}' missing")
                    all_valid = False
        except Exception as e:
            print(f"  ✗ Error parsing YAML: {e}")
            all_valid = False
    
    print("\n" + "="*60)
    if all_valid:
        print("✓ All validations passed!")
        print("="*60)
        return 0
    else:
        print("✗ Some validations failed")
        print("="*60)
        return 1

if __name__ == '__main__':
    sys.exit(main())
