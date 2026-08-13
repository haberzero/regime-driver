def parse(text, delimiter=",", comments=False):
    if not text:
        return []
    if text[0] == "\ufeff":
        text = text[1:]
    if not text:
        return []

    rows = []
    record = []
    field = ""
    in_quotes = False
    started = False
    quote_line = 1
    line = 1
    n = len(text)
    i = 0

    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field += '"'
                    i += 2
                else:
                    in_quotes = False
                    i += 1
            elif ch == "\n":
                field += "\n"
                i += 1
                line += 1
            elif ch == "\r":
                if i + 1 < n and text[i + 1] == "\n":
                    i += 2
                else:
                    i += 1
                field += "\n"
                line += 1
            else:
                field += ch
                i += 1
        elif ch == delimiter:
            record.append(field)
            field = ""
            started = True
            i += 1
        elif ch == '"':
            if field == "":
                in_quotes = True
                quote_line = line
                started = True
                i += 1
            else:
                field += '"'
                i += 1
        elif ch == "\n":
            if started:
                record.append(field)
                rows.append(record)
            record = []
            field = ""
            started = False
            i += 1
            line += 1
        elif ch == "\r":
            if started:
                record.append(field)
                rows.append(record)
            record = []
            field = ""
            started = False
            if i + 1 < n and text[i + 1] == "\n":
                i += 2
            else:
                i += 1
            line += 1
        elif comments and field == "" and not started and ch == "#":
            while i < n and text[i] != "\n":
                i += 1
        else:
            field += ch
            started = True
            i += 1

    if in_quotes:
        raise ValueError("unclosed quote at line %d" % quote_line)

    if started:
        record.append(field)
        rows.append(record)

    return rows
