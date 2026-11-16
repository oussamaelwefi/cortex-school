from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.config import settings

TEMPLATES_DIR = settings.ROOT_PATH / "prompts" / "templates"


def render_template(template_path: str, context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(default=False),
    )
    template = env.get_template(f"{template_path}.jinja2")
    return template.render(**context)
