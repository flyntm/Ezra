from pathlib import Path
import base64
import tempfile
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile

from presentations.lesson_presentation import discover_presentation
from presentations.powerpoint import (
    PowerPointDeck,
    ordered_slide_parts,
    part_relationships,
)
from presentations.browser_slideshow import render_pptx_html


class PowerPointRelationshipTests(unittest.TestCase):
    def setUp(self):
        self.original = discover_presentation()
        self.deck = PowerPointDeck.load(self.original)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.copy = Path(self.directory.name) / "edited.pptx"

    def write_copy(self, edits):
        with zipfile.ZipFile(self.original) as source, zipfile.ZipFile(
            self.copy, "w"
        ) as target:
            for name in source.namelist():
                target.writestr(name, edits.get(name, source.read(name)))

    def test_reordered_slides_keep_narration_and_rendering_in_same_order(self):
        with zipfile.ZipFile(self.original) as source:
            root = ET.fromstring(source.read("ppt/presentation.xml"))
        slides = root.find(
            "{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst"
        )
        slides[:] = list(reversed(slides))
        self.write_copy({"ppt/presentation.xml": ET.tostring(root)})
        self.assertEqual(
            PowerPointDeck.load(self.copy).notes, tuple(reversed(self.deck.notes))
        )
        pattern = r'<section class="slide"[^>]*>(.*?)</section>'
        original = re.findall(pattern, render_pptx_html(self.original), flags=re.S)
        edited = re.findall(pattern, render_pptx_html(self.copy), flags=re.S)
        self.assertEqual(edited, list(reversed(original)))

    def test_note_relationship_can_use_nonmatching_part_number(self):
        with zipfile.ZipFile(self.original) as source:
            parts = ordered_slide_parts(source)
            first = parts[0]
            second_note = next(
                target
                for kind, target in part_relationships(source, parts[1]).values()
                if kind.endswith("/notesSlide")
            )
            rel_path = str(Path(first).parent / "_rels" / (Path(first).name + ".rels"))
            root = ET.fromstring(source.read(rel_path))
            for node in root:
                if node.get("Type", "").endswith("/notesSlide"):
                    node.set("Target", "/" + second_note)
        self.write_copy({rel_path: ET.tostring(root)})
        self.assertEqual(PowerPointDeck.load(self.copy).notes[0], self.deck.notes[1])

    def test_browser_renders_embedded_picture_relationship(self):
        drawing = "http://schemas.openxmlformats.org/drawingml/2006/main"
        presentation = "http://schemas.openxmlformats.org/presentationml/2006/main"
        relationships = (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        )
        package_relationships = (
            "http://schemas.openxmlformats.org/package/2006/relationships"
        )
        image = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jTioAAAAASUVORK5CYII="
        )
        picture_deck = Path(self.directory.name) / "picture.pptx"

        with zipfile.ZipFile(picture_deck, "w") as package:
            package.writestr(
                "ppt/presentation.xml",
                f'<p:presentation xmlns:p="{presentation}" xmlns:r="{relationships}">'
                '<p:sldSz cx="9144000" cy="5143500"/>'
                '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>'
                "</p:presentation>",
            )
            package.writestr(
                "ppt/_rels/presentation.xml.rels",
                f'<Relationships xmlns="{package_relationships}">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
                'Target="slides/slide1.xml"/></Relationships>',
            )
            package.writestr(
                "ppt/slides/slide1.xml",
                f'<p:sld xmlns:p="{presentation}" xmlns:a="{drawing}" '
                f'xmlns:r="{relationships}"><p:cSld><p:spTree>'
                "<p:nvGrpSpPr/><p:grpSpPr/>"
                '<p:pic><p:nvPicPr><p:cNvPr id="2" name="Test photo" descr="A test photo"/>'
                "<p:cNvPicPr/><p:nvPr/></p:nvPicPr>"
                '<p:blipFill><a:blip r:embed="rIdImage"/>'
                "<a:stretch><a:fillRect/></a:stretch></p:blipFill>"
                '<p:spPr><a:xfrm><a:off x="914400" y="457200"/>'
                '<a:ext cx="1828800" cy="914400"/></a:xfrm>'
                '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
                "</p:pic></p:spTree></p:cSld></p:sld>",
            )
            package.writestr(
                "ppt/slides/_rels/slide1.xml.rels",
                f'<Relationships xmlns="{package_relationships}">'
                '<Relationship Id="rIdImage" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                'Target="../media/photo.png"/></Relationships>',
            )
            package.writestr("ppt/media/photo.png", image)

        rendered = render_pptx_html(picture_deck)

        self.assertIn('alt="A test photo"', rendered)
        self.assertIn("data:image/png;base64,", rendered)
        self.assertIn(
            "left:160.000px;top:80.000px;width:320.000px;height:160.000px", rendered
        )
