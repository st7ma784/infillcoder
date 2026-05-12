########################################################################################################################
# OctoPrint plugin installer for InfillCode.
#
# Two install modes:
#   editable:  pip install -e /path/to/QRPrintPlugin/octoprint_plugin
#   tarball:   pip install infillcode-X.Y.Z.tar.gz  (or OctoPrint Plugin Manager)
########################################################################################################################

plugin_identifier   = "infillcode"
plugin_package      = "infillcode"
plugin_name         = "InfillCode"
plugin_version      = "0.2.0"
plugin_description  = "GCode layer fingerprinting via infill line spacing modulation"
plugin_author       = "Dr Steve Mander"
plugin_author_email = ""
plugin_url          = "https://github.com/st7ma784/infillcoder"
plugin_license      = "MIT"
plugin_requires     = [
    "reedsolo>=1.7.0",
    "opencv-python-headless>=4.9.0",
]

########################################################################################################################

import os
import shutil
from setuptools import setup
from setuptools.command.sdist import sdist as _sdist

HERE      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
CORE_SRC  = os.path.join(REPO_ROOT, "core")


class sdist(_sdist):
    """Bundle core/ into the plugin tree so tarball installs are self-contained."""

    _bundle_dst = os.path.join(HERE, "infillcode", "_bundled_core")
    _egg_info   = os.path.join(HERE, "infillcode.egg-info")

    def run(self):
        copied = False
        if os.path.isdir(CORE_SRC) and not os.path.exists(self._bundle_dst):
            shutil.copytree(CORE_SRC, self._bundle_dst)
            copied = True

        # sdist needs relative paths in package_dir so SOURCES.txt is correct.
        orig_pkg_dir = dict(self.distribution.package_dir or {})
        self.distribution.package_dir = {
            "infillcode": "infillcode",
            "core":       os.path.join("infillcode", "_bundled_core"),
        }
        if os.path.isdir(self._egg_info):
            shutil.rmtree(self._egg_info)

        try:
            super().run()
        finally:
            self.distribution.package_dir = orig_pkg_dir
            if copied and os.path.exists(self._bundle_dst):
                shutil.rmtree(self._bundle_dst)


_bundled = os.path.join(HERE, "infillcode", "_bundled_core")
if os.path.isdir(_bundled):
    package_dir_map = {
        "infillcode": "infillcode",
        "core":       os.path.join("infillcode", "_bundled_core"),
    }
else:
    package_dir_map = {
        "infillcode": os.path.join(HERE, "infillcode"),
        "core":       CORE_SRC,
    }

setup(
    name=plugin_name,
    version=plugin_version,
    description=plugin_description,
    long_description=open(os.path.join(HERE, "..", "README.md"), encoding="utf-8").read()
        if os.path.isfile(os.path.join(HERE, "..", "README.md")) else "",
    long_description_content_type="text/markdown",
    author=plugin_author,
    author_email=plugin_author_email,
    url=plugin_url,
    license=plugin_license,
    keywords=["octoprint", "gcode", "3dprinting", "resume", "fingerprint", "recovery"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Plugins",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: Printing",
    ],
    packages=["infillcode", "core"],
    package_dir=package_dir_map,
    install_requires=plugin_requires,
    entry_points={
        "octoprint.plugin": [
            "{} = {}".format(plugin_identifier, plugin_package)
        ]
    },
    package_data={
        "infillcode": [
            "templates/*.jinja2",
            "templates/**/*.jinja2",
            "static/*.js",
            "static/*.css",
        ],
    },
    cmdclass={"sdist": sdist},
)
