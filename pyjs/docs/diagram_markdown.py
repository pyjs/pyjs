import re

from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor

from .diagrams import render_diagram

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


class _DiagramFences(Preprocessor):
    def run(self, lines):
        output = []
        index = 0
        while index < len(lines):
            match = FENCE.match(lines[index])
            if match is None:
                output.append(lines[index])
                index += 1
                continue
            fence, language = match.groups()
            end = index + 1
            closing = re.compile(r"^ {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*$")
            while end < len(lines) and not closing.fullmatch(lines[end]):
                end += 1
            if language.strip() == "diagram":
                if end == len(lines):
                    raise ValueError(f"Markdown line {index + 1}: unclosed diagram fence")
                try:
                    svg = render_diagram("\n".join(lines[index + 1:end]))
                except ValueError as error:
                    raise ValueError(f"Markdown line {index + 1}: {error}") from error
                output.extend(["", self.md.htmlStash.store(svg), ""])
            else:
                # Skip the entire outer fence so examples of diagrams stay code.
                output.extend(lines[index:end + 1])
            index = end + 1
        return output


class DiagramExtension(Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(_DiagramFences(md), "pyjs_diagrams", 26)
