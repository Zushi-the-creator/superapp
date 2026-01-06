# Contributing to NASDAQ Super App

Thank you for your interest in contributing! This project welcomes contributions from the community.

## How to Contribute

### Reporting Bugs

1. Check if the issue already exists in [Issues](https://github.com/yourusername/nasdaq-super-app/issues)
2. If not, create a new issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected vs actual behavior
   - Screenshots if applicable
   - Environment details (OS, Docker version, etc.)

### Suggesting Features

1. Open a new issue with the `enhancement` label
2. Describe the feature and its benefits
3. Provide examples or mockups if possible

### Pull Requests

1. Fork the repository
2. Create a new branch: `git checkout -b feature/your-feature-name`
3. Make your changes
4. Test thoroughly
5. Commit with clear messages: `git commit -m "Add: feature description"`
6. Push to your fork: `git push origin feature/your-feature-name`
7. Open a Pull Request

### Code Style

#### Python (Backend)
- Follow PEP 8
- Use type hints
- Add docstrings for functions/classes
- Run `black` for formatting: `black backend/`

#### TypeScript (Frontend)
- Follow ESLint rules
- Use TypeScript strict mode
- Use functional components
- Add prop types

#### Git Commits
- Use conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, etc.
- Keep commits atomic and focused
- Write clear commit messages

### Development Setup

```bash
# Clone your fork
git clone https://github.com/yourusername/nasdaq-super-app.git
cd nasdaq-super-app

# Start development environment
docker-compose up -d

# Backend development (with hot reload)
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend development (with hot reload)
cd frontend
npm install
npm run dev
```

### Testing

```bash
# Backend tests
cd backend
python -m pytest tests/

# Frontend tests
cd frontend
npm test
```

### Areas for Contribution

We especially welcome contributions in these areas:

- **Historical Charts**: Implement price charts with Recharts
- **Additional Indicators**: MACD, Bollinger Bands, etc.
- **Backtesting**: Test strategies on historical data
- **Options Analysis**: Add options chain data
- **Performance Optimization**: Improve scanner speed
- **Documentation**: Improve guides and tutorials
- **Tests**: Increase test coverage
- **UI/UX**: Enhance design and user experience

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers
- Accept constructive criticism
- Focus on what's best for the project
- Show empathy towards others

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Questions?

Open a discussion in [GitHub Discussions](https://github.com/yourusername/nasdaq-super-app/discussions).

Thank you for contributing! 🙏
