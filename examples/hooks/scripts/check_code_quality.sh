#!/bin/bash
#
# Code Quality Check Hook Script
#
# Runs various code quality checks after file modifications
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Get the project root directory
PROJECT_ROOT="${AMCP_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_ROOT"

print_status $YELLOW "🔍 Running code quality checks..."

# Python projects
if [ -f "pyproject.toml" ] || [ -f "setup.py" ] || [ -f "requirements.txt" ]; then
    print_status $YELLOW "🐍 Checking Python code quality..."
    
    # Black formatting check
    if command_exists black; then
        if black --check --diff . 2>/dev/null; then
            print_status $GREEN "✅ Black formatting check passed"
        else
            print_status $YELLOW "⚠️  Black formatting issues found"
        fi
    fi
    
    # isort import sorting check
    if command_exists isort; then
        if isort --check-only --diff . 2>/dev/null; then
            print_status $GREEN "✅ Import sorting check passed"
        else
            print_status $YELLOW "⚠️  Import sorting issues found"
        fi
    fi
    
    # Ruff linting
    if command_exists ruff; then
        if ruff check . 2>/dev/null; then
            print_status $GREEN "✅ Ruff linting check passed"
        else
            print_status $YELLOW "⚠️  Ruff linting issues found"
        fi
    fi
    
    # mypy type checking (if configured)
    if [ -f "mypy.ini" ] || [ -f ".mypyrc" ] || grep -q "\[tool.mypy\]" pyproject.toml 2>/dev/null; then
        if command_exists mypy; then
            if mypy . 2>/dev/null; then
                print_status $GREEN "✅ MyPy type checking passed"
            else
                print_status $YELLOW "⚠️  MyPy type checking issues found"
            fi
        fi
    fi
fi

# JavaScript/TypeScript projects
if [ -f "package.json" ]; then
    print_status $YELLOW "🟨 Checking JavaScript/TypeScript code quality..."
    
    # ESLint check
    if command_exists eslint && [ -f ".eslintrc.js" -o -f ".eslintrc.json" -o -f "eslint.config.js" ]; then
        if eslint . 2>/dev/null; then
            print_status $GREEN "✅ ESLint check passed"
        else
            print_status $YELLOW "⚠️  ESLint issues found"
        fi
    fi
    
    # Prettier formatting check
    if command_exists prettier && [ -f ".prettierrc" -o -f ".prettierrc.json" -o -f "prettier.config.js" ]; then
        if prettier --check . 2>/dev/null; then
            print_status $GREEN "✅ Prettier formatting check passed"
        else
            print_status $YELLOW "⚠️  Prettier formatting issues found"
        fi
    fi
fi

# Go projects
if [ -f "go.mod" ]; then
    print_status $YELLOW "🐹 Checking Go code quality..."
    
    # go fmt check
    if ! go fmt ./... 2>/dev/null; then
        print_status $GREEN "✅ go fmt check passed"
    else
        print_status $YELLOW "⚠️  go fmt issues found"
    fi
    
    # go vet check
    if go vet ./... 2>/dev/null; then
        print_status $GREEN "✅ go vet check passed"
    else
        print_status $YELLOW "⚠️  go vet issues found"
    fi
    
    # golint check (if available)
    if command_exists golint; then
        if golint ./... 2>/dev/null; then
            print_status $GREEN "✅ golint check passed"
        else
            print_status $YELLOW "⚠️  golint issues found"
        fi
    fi
fi

# Rust projects
if [ -f "Cargo.toml" ]; then
    print_status $YELLOW "🦀 Checking Rust code quality..."
    
    # cargo fmt check
    if cargo fmt --all -- --check 2>/dev/null; then
        print_status $GREEN "✅ cargo fmt check passed"
    else
        print_status $YELLOW "⚠️  cargo fmt issues found"
    fi
    
    # cargo clippy check
    if cargo clippy --all-targets --all-features -- -D warnings 2>/dev/null; then
        print_status $GREEN "✅ cargo clippy check passed"
    else
        print_status $YELLOW "⚠️  cargo clippy issues found"
    fi
fi

# General checks
print_status $YELLOW "🔍 Running general checks..."

# Check for large files (>1MB)
large_files=$(find . -type f -size +1M -not -path "./.git/*" -not -path "./node_modules/*" -not -path "./target/*" 2>/dev/null || true)
if [ -n "$large_files" ]; then
    print_status $YELLOW "⚠️  Large files found:"
    echo "$large_files" | head -5
else
    print_status $GREEN "✅ No large files found"
fi

# Check for common security issues in configuration files
if [ -f ".env" ]; then
    print_status $YELLOW "⚠️  .env file found - ensure it's not committed"
fi

if [ -f "id_rsa" ] || [ -f "id_ed25519" ]; then
    print_status $RED "❌ Private SSH keys found in repository!"
fi

print_status $GREEN "✅ Code quality checks completed"