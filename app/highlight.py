from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor
from PyQt6.QtCore import QRegularExpression


class SyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document, file_ext=".asm"):
        super().__init__(document)
        self.rules = []

        blue_fmt = QTextCharFormat()
        blue_fmt.setForeground(QColor("#569cd6"))

        yellow_fmt = QTextCharFormat()
        yellow_fmt.setForeground(QColor("#dcdcaa"))

        purple_fmt = QTextCharFormat()
        purple_fmt.setForeground(QColor("#c586c0"))

        green_fmt = QTextCharFormat()
        green_fmt.setForeground(QColor("#6a9955"))

        orange_fmt = QTextCharFormat()
        orange_fmt.setForeground(QColor("#ce9178"))

        if file_ext in ['.asm', '.s', '.inc']:
            instructions = [r"\bmov\b", r"\bint\b", r"\bjmp\b", r"\bcall\b", r"\bret\b",
                            r"\bpush\b", r"\bpop\b", r"\badd\b", r"\bsub\b", r"\bcmp\b", r"\bjc\b"]
            for ins in instructions:
                self.rules.append((QRegularExpression(ins), blue_fmt))

            registers = [r"\b[er]?[abcd]x\b", r"\b[abcd][lh]\b", r"\b[er]?[sb]p\b", r"\b[er]?[sd]i\b"]
            for reg in registers:
                self.rules.append((QRegularExpression(reg), yellow_fmt))

            directives = [r"\bdb\b", r"\bdw\b", r"\bdd\b", r"\bequ\b", r"\borg\b", r"\btimes\b"]
            for d in directives:
                self.rules.append((QRegularExpression(d), purple_fmt))

            self.rules.append((QRegularExpression(r";[^\n]*"), green_fmt))

        elif file_ext in ['.c', '.h', '.cpp']:
            c_keywords = [r"\bif\b", r"\belse\b", r"\bwhile\b", r"\bfor\b", r"\breturn\b", r"\binclude\b"]
            for k in c_keywords:
                self.rules.append((QRegularExpression(k), blue_fmt))

            c_types = [r"\bint\b", r"\bchar\b", r"\bvoid\b", r"\bfloat\b", r"\bstruct\b"]
            for t in c_types:
                self.rules.append((QRegularExpression(t), yellow_fmt))

            self.rules.append((QRegularExpression(r'//[^\n]*'), green_fmt))
            self.rules.append((QRegularExpression(r'/\*.*\*/'), green_fmt))

        elif file_ext == '.json':
            self.rules.append((QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"(?=\s*:)'), purple_fmt))
            self.rules.append((QRegularExpression(r'\b(true|false|null)\b'), blue_fmt))

        self.rules.append((QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"'), orange_fmt))
        self.rules.append((QRegularExpression(r'\b[0-9]+\b'), yellow_fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)