# Contributing to MSFS A330 WinWing MCDU Scraper

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

## Code of Conduct

- Be respectful and constructive
- Focus on what's best for the project
- Accept constructive criticism
- Help others learn and grow

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
