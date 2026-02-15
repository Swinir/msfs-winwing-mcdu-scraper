# Building Executables

Guide for building Windows executables from source.

## Prerequisites

- Python 3.8 or higher
- Git (for cloning repository)
- Windows OS (for building Windows executables)

## Quick Build (Local)

### Windows

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

2. **Run build script**:
   ```bash
   build_exe.bat
   ```

3. **Find executables** in `dist/` folder:
   - `MSFS-MCDU-Scraper-GUI.exe`
   - `MSFS-MCDU-Scraper-CLI.exe`

### Using PyInstaller Directly

**Build GUI**:
```bash
pyinstaller --clean gui.spec
```

**Build CLI**:
```bash
pyinstaller --clean cli.spec
```

## GitHub Actions (Automatic)

The repository includes a GitHub Actions workflow that automatically builds executables when you:

1. **Push a version tag**:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

2. **Manually trigger** the workflow from GitHub Actions tab

### What the Workflow Does

1. Sets up Windows build environment
2. Installs Python and dependencies
3. Installs Tesseract OCR
4. Builds both GUI and CLI executables
5. Packages with documentation
6. Creates ZIP archive
7. Uploads as artifact
8. Creates GitHub release (for tags)

## Build Configuration

### PyInstaller Spec Files

Two spec files control the build:

**gui.spec** - GUI Application:
- Single file executable
- No console window (`console=False`)
- Includes documentation and config examples
- Bundles all dependencies

**cli.spec** - CLI Application:
- Single file executable
- Console window (`console=True`)
- Minimal dependencies
- Bundles config example

### Customizing Builds

Edit the spec files to:
- Add application icon (`icon='path/to/icon.ico'`)
- Include additional data files
- Exclude unnecessary modules
- Add version information

Example - Adding an icon:
```python
exe = EXE(
    # ... other parameters ...
    icon='path/to/icon.ico',  # Add this line
    # ... other parameters ...
)
```

## Package Contents

The release package includes:

```
MSFS-MCDU-Scraper-Windows.zip
├── MSFS-MCDU-Scraper-GUI.exe     # GUI executable
├── MSFS-MCDU-Scraper-CLI.exe     # CLI executable
├── README.md                      # Main documentation
├── README-EXECUTABLE.txt          # Quick start for executable users
├── QUICKSTART.md                  # Quick start guide
├── LICENSE                        # MIT License
├── config.yaml.example            # Example configuration
└── docs/                          # Documentation folder
    ├── SETUP.md
    ├── CALIBRATION.md
    ├── VISUAL_GUIDE.md
    ├── GUI_GUIDE.md
    └── GUI_PREVIEW.md
```

## Troubleshooting Builds

### Missing Modules

**Error**: `ModuleNotFoundError` during build

**Solution**: Add to `hiddenimports` in spec file:
```python
hiddenimports=[
    'your_module_name',
    # ... existing imports ...
],
```

### Large Executable Size

**Causes**:
- Including unnecessary libraries
- Not using UPX compression

**Solutions**:
1. Enable UPX: `upx=True` in spec file
2. Exclude unused modules: Add to `excludes` list
3. Use `--onefile` mode (already enabled)

### Runtime Errors

**Error**: Executable runs but crashes

**Debug steps**:
1. Build with console enabled: `console=True`
2. Check for missing data files
3. Verify all imports are included in `hiddenimports`
4. Test with `--onedir` mode first (easier debugging)

**Common issues**:
- Missing Tesseract installation
- Config file not bundled
- DLL dependencies missing

### Tesseract Not Found

**Error**: `TesseractNotFoundError` when running executable

**Solution**: 
- Users must install Tesseract OCR separately
- Include instructions in README-EXECUTABLE.txt
- Can't bundle Tesseract due to license/size

## Version Information

To add version info to executables:

1. Create `version.rc` file:
   ```
   VSVersionInfo(
     ffi=FixedFileInfo(
       filevers=(1, 0, 0, 0),
       prodvers=(1, 0, 0, 0),
       # ...
     ),
     # ...
   )
   ```

2. Update spec file:
   ```python
   exe = EXE(
       # ... other parameters ...
       version='version.rc',
   )
   ```

## Platform-Specific Notes

### Windows

- Builds work natively
- Include pywin32 for window capture
- Tesseract must be installed separately

### Linux/Mac

- Can build Linux/Mac executables
- Window capture won't work (Windows-only)
- Screen region capture still works
- Use Wine for Windows builds (not recommended)

## CI/CD Integration

### GitHub Actions Workflow

Located at: `.github/workflows/build-executable.yml`

**Triggers**:
- Version tags (`v*`)
- Manual workflow dispatch

**Outputs**:
- Artifact: `MSFS-MCDU-Scraper-Windows.zip`
- Release asset (for tags)

### Creating a Release

1. **Update version** in code/docs
2. **Commit changes**:
   ```bash
   git add .
   git commit -m "Release v1.0.0"
   ```
3. **Create and push tag**:
   ```bash
   git tag -a v1.0.0 -m "Version 1.0.0"
   git push origin v1.0.0
   ```
4. **GitHub Actions** automatically builds and creates release
5. **Download** from Releases page

## Best Practices

### Before Building

- [ ] Test application locally
- [ ] Update version numbers
- [ ] Update documentation
- [ ] Run linters and tests
- [ ] Test with clean Python environment

### Testing Executables

- [ ] Run on clean Windows VM
- [ ] Test without Python installed
- [ ] Verify Tesseract requirement
- [ ] Test both GUI and CLI versions
- [ ] Check all features work
- [ ] Verify config file handling

### Release Checklist

- [ ] Update CHANGELOG
- [ ] Update version in code
- [ ] Update README with new features
- [ ] Tag release in git
- [ ] Wait for GitHub Actions build
- [ ] Test downloaded executable
- [ ] Update release notes if needed

## Advanced Options

### Code Signing

To sign executables (requires certificate):

```bash
signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com MSFS-MCDU-Scraper-GUI.exe
```

### Installer Creation

Use tools like Inno Setup to create installer:
1. Install Inno Setup
2. Create `.iss` script
3. Include Tesseract installer
4. Bundle executables and docs
5. Build setup.exe

### Multi-Platform Builds

GitHub Actions can build for multiple platforms:
```yaml
strategy:
  matrix:
    os: [windows-latest, ubuntu-latest, macos-latest]
runs-on: ${{ matrix.os }}
```

## Resources

- [PyInstaller Documentation](https://pyinstaller.org/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Python Packaging Guide](https://packaging.python.org/)

## Getting Help

If you encounter build issues:
1. Check this guide
2. Review PyInstaller logs
3. Check GitHub Actions logs
4. Open an issue with:
   - Build command used
   - Error messages
   - Python version
   - OS version
