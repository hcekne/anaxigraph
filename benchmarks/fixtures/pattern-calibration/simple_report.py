"""One fixed report renderer that has no provider variation to abstract."""


def render_report(title: str, rows: list[str]) -> str:
    heading = f"# {title}"
    return "\n".join([heading, *[f"- {row}" for row in rows]])
