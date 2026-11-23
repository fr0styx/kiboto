"""The list of third-party packages in the image, with their licences (scripts/third_party.py)."""

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("third_party", ROOT / "scripts" / "third_party.py")
tp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tp)


class Meta(dict):
    def __init__(self, classifiers=(), **kw):
        super().__init__(**kw)
        self.classifiers = list(classifiers)

    def get_all(self, key):
        return self.classifiers if key == "Classifier" else None


def test_a_licence_is_read_from_what_the_package_says():
    assert tp._python_licence(Meta(**{"License-Expression": "Apache-2.0"})) == "Apache-2.0"
    assert tp._python_licence(Meta(["License :: OSI Approved :: MIT License"])) == "MIT License"
    assert tp._python_licence(Meta(License="BSD")) == "BSD"
    assert tp._python_licence(Meta(License="a very long licence text\nwith lines")) == tp.UNKNOWN
    assert tp._python_licence(Meta()) == tp.UNKNOWN


def test_the_installed_python_packages_are_listed():
    rows = tp.python_packages()
    names = {n.lower() for n, _, _ in rows}
    assert {"fastapi", "pydantic"} <= names and len(names) == len(rows)


def test_only_the_frontend_packages_the_pages_use_are_listed(tmp_path):
    lock = tmp_path / "package-lock.json"
    lock.write_text(
        json.dumps(
            {
                "packages": {
                    "": {"name": "kiboto"},
                    "node_modules/chart.js": {"version": "4.6.1", "license": "MIT"},
                    "node_modules/a/node_modules/b": {"version": "1.0.0"},
                    "node_modules/vite": {"version": "7.0.0", "license": "MIT", "dev": True},
                    "node_modules/opt": {"version": "1.0.0", "license": "MIT", "devOptional": True},
                }
            }
        )
    )
    assert tp.frontend_packages(str(lock)) == [("b", "1.0.0", tp.UNKNOWN), ("chart.js", "4.6.1", "MIT")]
    text = tp.render([("fastapi", "0.165.0", "MIT")], tp.frontend_packages(str(lock)))
    assert "fastapi 0.165.0: MIT" in text and "Frontend packages (2)" in text and "MIT licence" in text


def test_it_writes_the_list(tmp_path, capsys):
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps({"packages": {"node_modules/qrcode": {"version": "1.5.4", "license": "MIT"}}}))
    assert tp.main(["third_party.py", str(lock)]) == 0
    assert "qrcode 1.5.4: MIT" in capsys.readouterr().out
    assert tp.main(["third_party.py"]) == 0 and "Frontend packages (0)" in capsys.readouterr().out
