# Contributing to LetterMonstr

Thank you for your interest in contributing to LetterMonstr! This document provides guidelines and instructions to help you contribute effectively to this project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Important Notes About This Project](#important-notes-about-this-project)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Pull Request Process](#pull-request-process)
- [Coding Guidelines](#coding-guidelines)
- [Testing](#testing)
- [Documentation](#documentation)
- [Communication](#communication)

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for everyone. Please:

- Use welcoming and inclusive language
- Be respectful of differing viewpoints and experiences
- Gracefully accept constructive criticism
- Focus on what is best for the community
- Show empathy towards other community members

## Important Notes About This Project

LetterMonstr is specifically designed for macOS environments. When contributing, please keep in mind:

- The application is intended for local use on macOS only
- It is not designed for or tested on Windows, Linux, or server environments
- The focus is on personal use rather than production/enterprise deployment
- Compatibility with macOS (10.15 Catalina and later) must be maintained

## Getting Started

### Prerequisites

- macOS 10.15 Catalina or later
- Python 3.9+
- Git
- A Gmail account for testing (recommended to use a separate testing account)
- Anthropic API key (for Claude integration)

### Setup Process

1. **Fork the repository**
   - Click the "Fork" button at the top right of the repository page

2. **Clone your fork**

   ```bash
   git clone https://github.com/YOUR-USERNAME/lettermonstr.git
   cd lettermonstr
   ```

3. **Set up a virtual environment**

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

4. **Install dependencies**

   ```bash
   pip3 install -r requirements.txt
   ```

5. **Create your configuration**

   ```bash
   python3 setup_config.py
   ```

   - Use test credentials for your development environment
   - Consider using a dedicated Gmail account for testing

## Development Workflow

1. **Create a branch for your feature or bugfix**

   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/issue-you-are-fixing
   ```

2. **Make your changes**
   - Focus on a single feature/fix per branch
   - Follow the coding guidelines (see below)
   - Add appropriate comments and docstrings

3. **Test your changes locally**
   - Ensure the application still runs properly on macOS
   - Use `test_newsletter.py` to test the email processing pipeline
   - Manually verify that your changes work as expected

4. **Commit your changes with clear commit messages**

   ```bash
   git commit -m "Clear description of your changes"
   ```

5. **Push your branch to your fork**

   ```bash
   git push origin feature/your-feature-name
   ```

6. **Create a pull request**
   - Go to the original LetterMonstr repository
   - Click "New pull request"
   - Choose "compare across forks"
   - Select your fork and branch
   - Fill in the PR template with details about your changes

## Pull Request Process

1. **PR Title and Description**
   - Use a clear, descriptive title
   - Include a summary of changes
   - Reference any related issues with "Fixes #issue_number"
   - Explain your approach and reasoning

2. **Review Process**
   - PRs require at least one review before merging
   - Address any feedback or requested changes
   - The maintainer may request specific changes before merging

3. **PR Checklist**
   - [ ] Code follows project style guidelines
   - [ ] Documentation is updated (if necessary)
   - [ ] Changes have been tested on macOS
   - [ ] Commit messages are clear and descriptive
   - [ ] Code doesn't contain sensitive information (API keys, passwords, etc.)

## Coding Guidelines

### Python Style

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) guidelines
- Use 4 spaces for indentation (no tabs)
- Maximum line length of 100 characters
- Use meaningful variable and function names
- Add docstrings to all functions, classes, and modules

### Project-Specific Guidelines

- Keep compatibility with macOS 10.15+ in mind
- Ensure email handling is secure and privacy-focused
- Any operations with external services should be respectful of API limits
- Don't hardcode sensitive information (use config files)
- Follow the existing project structure

## Testing

- Test all changes thoroughly on macOS
- Use the `test_newsletter.py` script to test the email processing pipeline
- For significant changes, add appropriate unit tests

## Documentation

- Update the README.md if your changes impact user-facing functionality
- Include comments explaining complex sections of code
- Keep docstrings up-to-date with changes to function signatures

## Communication

- Use GitHub Issues for bug reports and feature requests
- Provide clear context and reproducible steps for bugs
- For major changes, open an issue for discussion before submitting a PR

---

Thank you for contributing to LetterMonstr! Your efforts help make this tool better for everyone.
