import html
from io import StringIO
from pathlib import Path

import docutils.parsers.rst.directives
import jinja2
import pelican
import rst2text

DISPLAYED_ARTICLE_COUNT_ON_HOME = 10
TEMPLATE_HOME = """\
{{ TOP_PAGE_ASCII }}
{{ SITENAME }}
=============

Latest Articles
~~~~~~~~~~~~~~~
{% for i in range(articles_count_on_home) %}{% set article = articles[i] %}
* {{ article.date.strftime("%d/%m/%Y") }} {{ article.raw_title }}
  /{{ article.url | replace(".html", "") }}
{% endfor %}
{% if articles | length > articles_count_on_home %}
* /all ➕ All Articles
{% endif %}
"""

TEMPLATE_ARTICLES_INDEX_PAGE = """\
{{ TOP_PAGE_ASCII }}
All Articles — {{ SITENAME }}
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
{% for article in articles %}
* {{ article.date.strftime("%d/%m/%Y") }} {{ article.raw_title }}
  /{{ article.url | replace(".html", "") }}
{% endfor %}

-----------------------------------------------------------------------------------------

* / 🏠 Home
"""

TEMPLATE_ARTICLE = """\
{{ TOP_PAGE_ASCII }}
{{ article.raw_title }}
~~~~~~~~~~~~~~~~~~~~~~~
{{ article.date.strftime("%d/%m/%Y") }}

{{ article.content_gemtext }}

-----------------------------------------------------------------------------------------
* / 🏠 Home

"""


class PelicanTextWriter(rst2text.TextWriter):
    def __init__(self, generator, article):
        rst2text.TextWriter.__init__(self)
        self._generator = generator  # Pelican generator
        self._article = article  # Pelican article

    def _remove_first_title(self):
        for i in range(len(self.visitor.nodes)):
            node = self.visitor.nodes[i]
            if type(node) is rst2text.TitleNode and node.level == 1:
                self.visitor.nodes.pop(i)
                break

    def _remove_attach_tag_from_links(self):
        def _loop_on_nodes(nodes):
            for node in nodes:
                if isinstance(node, rst2text.NodeGroup):
                    _loop_on_nodes(node.nodes)
                elif isinstance(node, rst2text.LinkNode):
                    if node.uri.startswith("{attach}"):
                        node.uri = node.uri[8:]
                    if node.rawtext.startswith("{attach}"):
                        node.rawtext = node.uri[8:]

        _loop_on_nodes(self.visitor.nodes)

    def _clean_figure_links(self):
        def _loop_on_nodes(nodes):
            for node in nodes:
                if isinstance(node, rst2text.NodeGroup) and not isinstance(
                    node, rst2text.FigureNode
                ):
                    _loop_on_nodes(node.nodes)
                    continue
                if not isinstance(node, rst2text.FigureNode):
                    continue
                if len(node.nodes) < 2:
                    continue
                if not isinstance(node.nodes[0], rst2text.LinkNode):
                    continue
                if not isinstance(node.nodes[1], rst2text.LinkNode):
                    continue
                if node.nodes[0].uri.endswith(node.nodes[1].uri) or node.nodes[
                    1
                ].uri.endswith(node.nodes[0].uri):
                    if node.nodes[0].uri == node.nodes[0].rawtext:
                        node.nodes.pop(0)
                    elif node.nodes[1].uri == node.nodes[1].rawtext:
                        node.nodes.pop(1)

        _loop_on_nodes(self.visitor.nodes)

    def _resolve_internal_links(self):
        def _loop_on_nodes(nodes):
            for node in nodes:
                if isinstance(node, rst2text.NodeGroup):
                    _loop_on_nodes(node.nodes)
                    continue
                if not isinstance(node, rst2text.LinkNode):
                    continue
                if not node.uri.startswith("{filename}"):
                    continue
                article_path = Path(self._article.source_path)
                target_path = (article_path.parent / node.uri[10:]).resolve()
                for article in self._generator.articles:
                    if target_path.as_posix() == article.source_path:
                        target_uri = Path("/%s" % article.url)
                        node.uri = target_uri.as_posix()
                        break

        _loop_on_nodes(self.visitor.nodes)

    def _before_translate_output_generation_hook(self):
        self._remove_first_title()
        self._remove_attach_tag_from_links()
        self._clean_figure_links()
        self._resolve_internal_links()


def generate_article(generator, article, save_as):
    template_text = generator.settings.get("GEMINI_TEMPLATE_ARTICLE", TEMPLATE_ARTICLE)

    # XXX HACK: remove the Pelican custom "code-block" directive
    pelican_code_block = None
    if "code-block" in docutils.parsers.rst.directives._directives:
        pelican_code_block = docutils.parsers.rst.directives._directives["code-block"]
        del docutils.parsers.rst.directives._directives["code-block"]

    # Read and parse the reStructuredText file
    with open(article.source_path, "r") as rst_file:
        document = rst2text.parse_rst(rst_file.read(), rst_file.name)

    # Avoid HTML entities in titles
    article.raw_title = html.unescape(article.title)

    # Convert the reStructuredText into Gemtext
    writer = PelicanTextWriter(generator, article)
    gmi_io = StringIO()
    writer.write(document, gmi_io)
    gmi_io.seek(0)

    # Render the final Gemtext file (templating)
    article.content_gemtext = gmi_io.read()
    template = jinja2.Template(template_text)
    rendered_article = template.render(
        generator.context,
        article=article,
        GEMSITEURL=generator.settings.get("SITEURL", "")
        .replace("http://", "/")
        .replace("https://", "/"),
    )

    # Write the output file
    save_as.parent.mkdir(parents=True, exist_ok=True)
    with open(save_as, "w") as gmi_file:
        gmi_file.write(rendered_article)

    # XXX HACK: put-back the Pelican custom "code-block" directive
    pelican_code_block = None
    if pelican_code_block:
        docutils.parsers.rst.directives._directives["code-block"] = pelican_code_block


def generate_home_page(generator):
    save_as = Path(generator.output_path) / "index"
    template_text = generator.settings.get("GEMINI_TEMPLATE_HOME", TEMPLATE_HOME)
    articles_count_on_home = generator.settings.get(
        "GEMINI_DISPLAYED_ARTICLE_COUNT_ON_HOME", DISPLAYED_ARTICLE_COUNT_ON_HOME
    )

    # Render the page (templating)
    template = jinja2.Template(template_text)
    rendered_page = template.render(
        generator.context,
        articles_count_on_home=min(len(generator.articles), articles_count_on_home),
        GEMSITEURL=generator.settings.get("SITEURL", "")
        .replace("http://", "/")
        .replace("https://", "/"),
    )

    # Write the output file
    with open(save_as, "w") as gmi_file:
        gmi_file.write(rendered_page)


def generate_all_articles_page(generator):
    save_as = Path(generator.output_path) / "all"
    template_text = generator.settings.get(
        "GEMINI_TEMPLATE_ARTICLES_INDEX_PAGE", TEMPLATE_ARTICLES_INDEX_PAGE
    )

    # Render the page (templating)
    template = jinja2.Template(template_text)
    rendered_page = template.render(
        generator.context,
        GEMSITEURL=generator.settings.get("SITEURL", "")
        .replace("http://", "/")
        .replace("https://", "/"),
    )

    # Write the output file
    with open(save_as, "w") as gmi_file:
        gmi_file.write(rendered_page)


def article_generator_write_article(generator, content=None):
    save_as = Path(generator.output_path) / Path(content.save_as).with_suffix("")
    generate_article(generator, content, save_as)


def article_writer_finalized(generator, writer=None):
    generate_home_page(generator)
    generate_all_articles_page(generator)


def register():
    pelican.signals.article_generator_write_article.connect(
        article_generator_write_article
    )
    pelican.signals.article_writer_finalized.connect(article_writer_finalized)
