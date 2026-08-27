# Contributing to MSFS WinWing CDU Scraper

Thank you for your interest in contributing to this project!

## Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/msfs-winwing-mcdu-scraper.git
   ```
3. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Making Changes

1. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your changes
3. Test your changes thoroughly
4. Commit with clear messages:
   ```bash
   git commit -m "Add feature: brief description"
   ```
5. Push to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
6. Create a Pull Request

## Code Style

- Follow PEP 8 style guidelines
- Use meaningful variable and function names
- Add docstrings to all functions and classes
- Keep functions focused and single-purpose
- Add comments for complex logic

## Testing

Before submitting:

1. Validate syntax:
   ```bash
   python validate.py
   ```
2. Run unit tests:
   ```bash
   python -m unittest discover tests
   ```
3. Test with actual MSFS and WinWing hardware if possible

## Areas for Contribution

### High Priority
- Improved character recognition accuracy
- Better color detection algorithms
- Performance optimizations
- Template matching implementation

### Medium Priority
- Support for other aircraft (Boeing 737, etc.)
- Additional font support
- Better error handling
- Configuration GUI

### Documentation
- Additional setup guides
- Troubleshooting tips
- Video tutorials
- Translation to other languages

## Reporting Issues

When reporting bugs, please include:
- Python version
- Operating system
- MSFS version
- Error messages and logs
- Steps to reproduce
- Screenshots if applicable

## Feature Requests

Feature requests are welcome! Please:
- Check if it's already requested
- Describe the use case
- Explain expected behavior
- Consider implementation approach

## Running without the hardware

Setting `MSFS_SCRAPER_NO_MOBIFLIGHT=1` starts the GUI with the WebSocket
client replaced by one that accepts display data and throws it away.  The
capture, the parser and the log all behave normally, so it is the quickest
way to check recognition against a real pop-out with no WinWing CDU plugged
in — and the log pane says `Test mode: MobiFlight disabled` so it cannot be
mistaken for the real thing.

```
set MSFS_SCRAPER_NO_MOBIFLIGHT=1 && python src/gui.py
```

Keep it out of `run_gui.bat`.  That is the launcher QUICKSTART.md tells
users to double-click, and with the variable set there the scraper reads the
display perfectly and sends it nowhere, which looks exactly like broken
hardware.

## Code of Conduct

- Be respectful and constructive
- Focus on what's best for the project
- Accept constructive criticism
- Help others learn and grow

## License

By contributing, you agree that your contributions will be licensed under the PolyForm Noncommercial License 1.0.0, the same terms as the project.
