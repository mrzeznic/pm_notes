from markdown_it import MarkdownIt

content = """# My Project

## Tasks
- [ ] Task 1
- [x] Task 2 #p1
- [ ] Task 3
  with multiple lines
  and some more
- [ ] Task 4

## ARCHIVE
- [x] Task 0
"""

md = MarkdownIt()
tokens = md.parse(content)
lines = content.splitlines()

for t in tokens:
    if t.type == "list_item_open":
        start, end = t.map
        slice_lines = lines[start:end]
        first_line = slice_lines[0]
        if "- [" in first_line:
            print(f"Task found at lines {start}-{end}:")
            print(f"  First line: {first_line}")
            if len(slice_lines) > 1:
                print(f"  Body: {slice_lines[1:]}")
