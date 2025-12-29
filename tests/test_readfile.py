"""Tests for the indentation-aware reading functionality."""

import pytest
from pathlib import Path
import tempfile

from amcp.readfile import (
    IndentationOptions,
    read_file_with_indentation,
    read_file_with_ranges,
    _measure_indent,
    _compute_effective_indents,
    _collect_file_lines,
)


class TestMeasureIndent:
    """Tests for indentation measurement."""

    def test_spaces(self):
        assert _measure_indent("    hello") == 4
        assert _measure_indent("        world") == 8

    def test_tabs(self):
        assert _measure_indent("\thello") == 4  # TAB_WIDTH = 4
        assert _measure_indent("\t\tworld") == 8

    def test_mixed(self):
        assert _measure_indent("  \thello") == 6  # 2 spaces + 1 tab (4)

    def test_no_indent(self):
        assert _measure_indent("hello") == 0
        assert _measure_indent("") == 0


class TestReadFileWithRanges:
    """Tests for slice mode (ranges)."""

    def test_whole_file(self, tmp_path):
        file = tmp_path / "test.py"
        file.write_text("line1\nline2\nline3\n")

        blocks = read_file_with_ranges(file, [])
        assert len(blocks) == 1
        assert blocks[0]["start"] == 1
        assert blocks[0]["end"] == 3
        assert len(blocks[0]["lines"]) == 3

    def test_single_range(self, tmp_path):
        file = tmp_path / "test.py"
        file.write_text("line1\nline2\nline3\nline4\nline5\n")

        blocks = read_file_with_ranges(file, ["2-4"])
        assert len(blocks) == 1
        assert blocks[0]["start"] == 2
        assert blocks[0]["end"] == 4
        assert [(n, l) for n, l in blocks[0]["lines"]] == [
            (2, "line2"),
            (3, "line3"),
            (4, "line4"),
        ]

    def test_multiple_ranges(self, tmp_path):
        file = tmp_path / "test.py"
        file.write_text("line1\nline2\nline3\nline4\nline5\n")

        blocks = read_file_with_ranges(file, ["1-2", "4-5"])
        assert len(blocks) == 2
        assert blocks[0]["lines"][0] == (1, "line1")
        assert blocks[1]["lines"][0] == (4, "line4")


class TestReadFileWithIndentation:
    """Tests for indentation-aware mode."""

    def test_simple_function(self, tmp_path):
        """Test reading a simple function."""
        file = tmp_path / "test.py"
        file.write_text("""def hello():
    print("Hello")
    print("World")
    return True

def other():
    pass
""")
        # Anchor at line 2 (inside hello function)
        blocks = read_file_with_indentation(
            file, offset=2, limit=50,
            options=IndentationOptions(max_levels=1)
        )
        
        assert len(blocks) == 1
        lines = blocks[0]["lines"]
        line_numbers = [l[0] for l in lines]
        
        # Should capture the hello function
        assert 1 in line_numbers  # def hello():
        assert 2 in line_numbers  # print("Hello")
        assert 4 in line_numbers  # return True

    def test_nested_structure(self, tmp_path):
        """Test reading nested code structures."""
        file = tmp_path / "test.py"
        file.write_text("""class Calculator:
    def __init__(self):
        self.value = 0

    def add(self, x):
        if x > 0:
            self.value += x
        return self.value

    def subtract(self, x):
        self.value -= x
        return self.value
""")
        # Anchor at line 7 (self.value += x inside if)
        blocks = read_file_with_indentation(
            file, offset=7, limit=50,
            options=IndentationOptions(max_levels=1)
        )
        
        lines = blocks[0]["lines"]
        # Should capture the if block and the add method
        line_numbers = [l[0] for l in lines]
        assert 6 in line_numbers  # if x > 0:
        assert 7 in line_numbers  # self.value += x

    def test_max_levels_2(self, tmp_path):
        """Test with max_levels=2 to get more context."""
        file = tmp_path / "test.py"
        file.write_text("""class Calculator:
    def add(self, x):
        if x > 0:
            self.value += x
        return self.value
""")
        # Anchor at line 4 (self.value += x), max_levels=2
        blocks = read_file_with_indentation(
            file, offset=4, limit=50,
            options=IndentationOptions(max_levels=2)
        )
        
        lines = blocks[0]["lines"]
        line_numbers = [l[0] for l in lines]
        # Should include the class and method
        assert 2 in line_numbers  # def add(self, x):
        assert 3 in line_numbers  # if x > 0:
        assert 4 in line_numbers  # self.value += x

    def test_include_siblings(self, tmp_path):
        """Test including sibling blocks."""
        file = tmp_path / "test.py"
        file.write_text("""def first():
    pass

def second():
    pass

def third():
    pass
""")
        # Anchor at line 4 (def second)
        blocks_no_siblings = read_file_with_indentation(
            file, offset=5, limit=50,
            options=IndentationOptions(include_siblings=False)
        )
        
        blocks_with_siblings = read_file_with_indentation(
            file, offset=5, limit=50,
            options=IndentationOptions(include_siblings=True)
        )
        
        # Without siblings should just get second()
        lines_no_sib = [l[0] for l in blocks_no_siblings[0]["lines"]]
        # With siblings should get more
        lines_with_sib = [l[0] for l in blocks_with_siblings[0]["lines"]]
        
        assert len(lines_with_sib) > len(lines_no_sib)

    def test_include_header_comments(self, tmp_path):
        """Test including header comments."""
        file = tmp_path / "test.py"
        file.write_text("""# This is a module docstring

# This function does something important
def important_function():
    return 42
""")
        # Anchor at line 5 (return 42)
        blocks = read_file_with_indentation(
            file, offset=5, limit=50,
            options=IndentationOptions(max_levels=1, include_header=True)
        )
        
        lines = blocks[0]["lines"]
        line_contents = [l[1] for l in lines]
        
        # Should include the comment header
        assert any("important" in l for l in line_contents)

    def test_out_of_range_anchor(self, tmp_path):
        """Test with anchor line out of range."""
        file = tmp_path / "test.py"
        file.write_text("line1\nline2\n")

        with pytest.raises(ValueError, match="out of range"):
            read_file_with_indentation(
                file, offset=100, limit=50,
                options=IndentationOptions()
            )

    def test_empty_file(self, tmp_path):
        """Test reading empty file."""
        file = tmp_path / "empty.py"
        file.write_text("")

        blocks = read_file_with_indentation(
            file, offset=1, limit=50,
            options=IndentationOptions()
        )
        
        assert blocks[0]["lines"] == []

    def test_python_class(self, tmp_path):
        """Test reading a Python class structure."""
        file = tmp_path / "test.py"
        file.write_text("""import os
import sys

class MyClass:
    '''A sample class.'''
    
    def __init__(self, name):
        self.name = name
        self.items = []
    
    def add_item(self, item):
        '''Add an item to the list.'''
        if item is not None:
            self.items.append(item)
        return len(self.items)
    
    def clear(self):
        self.items = []

def standalone():
    pass
""")
        # Anchor at line 14 (self.items.append)
        blocks = read_file_with_indentation(
            file, offset=14, limit=100,
            options=IndentationOptions(max_levels=2)
        )
        
        lines = blocks[0]["lines"]
        line_numbers = [l[0] for l in lines]
        
        # Should include add_item method definition
        assert 11 in line_numbers  # def add_item
        assert 14 in line_numbers  # self.items.append
        assert 15 in line_numbers  # return len

    def test_javascript_style(self, tmp_path):
        """Test with JavaScript-style code."""
        file = tmp_path / "test.js"
        file.write_text("""function outer() {
    const cache = new Map();
    function inner(key) {
        if (!cache.has(key)) {
            cache.set(key, []);
        }
        return cache.get(key);
    }
    return inner;
}
""")
        # Anchor at line 5 (cache.set)
        blocks = read_file_with_indentation(
            file, offset=5, limit=50,
            options=IndentationOptions(max_levels=1)
        )
        
        lines = blocks[0]["lines"]
        line_numbers = [l[0] for l in lines]
        
        # Should capture the if block
        assert 4 in line_numbers  # if (!cache.has(key))
        assert 5 in line_numbers  # cache.set(key, [])
        assert 6 in line_numbers  # }


class TestEffectiveIndents:
    """Tests for effective indentation computation."""

    def test_blank_lines_inherit_indent(self, tmp_path):
        file = tmp_path / "test.py"
        content = """def func():
    line1

    line2
"""
        file.write_text(content)
        lines = content.splitlines()
        records = _collect_file_lines(lines)
        effective = _compute_effective_indents(records)
        
        # Blank line should inherit indent from line1
        assert effective[2] == 4  # Blank line
        assert effective[3] == 4  # line2


class TestReadFileToolIntegration:
    """Integration tests for ReadFileTool."""

    def test_slice_mode(self, tmp_path):
        from amcp.tools import ReadFileTool

        file = tmp_path / "test.py"
        file.write_text("line1\nline2\nline3\n")

        tool = ReadFileTool()
        result = tool.execute(str(file), ranges=["1-2"], mode="slice")

        assert result.success
        assert "line1" in result.content
        assert "line2" in result.content
        assert result.metadata["mode"] == "slice"

    def test_indentation_mode(self, tmp_path):
        from amcp.tools import ReadFileTool

        file = tmp_path / "test.py"
        file.write_text("""def hello():
    print("Hello")
    return True

def other():
    pass
""")

        tool = ReadFileTool()
        result = tool.execute(
            str(file),
            mode="indentation",
            offset=2,
            max_levels=1,
        )

        assert result.success
        assert "indentation mode" in result.content
        assert result.metadata["mode"] == "indentation"
        # Should capture the hello function
        assert "hello" in result.content
        assert "print" in result.content
