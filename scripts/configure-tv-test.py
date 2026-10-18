"""Enable sharing of the generated TV test clip through the local control API."""
import pathlib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


def main():
    root = pathlib.Path(__file__).resolve().parents[1]
    folder = root / "build" / "TV Test"
    if not (folder / "Library Share - TV Test.mp4").is_file():
        raise SystemExit("Generate the TV test clip before configuring this share.")
    token = (root / "build/library.json.control-token").read_text().strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for action in ("add", "enable"):
        parameters = {"token": token, "action": action}
        if action == "add":
            parameters["folder"] = str(folder)
        try:
            with opener.open("http://127.0.0.1:57642/local?" + urllib.parse.urlencode(parameters), timeout=10) as response:
                status = ET.fromstring(response.read())
        except OSError:
            raise SystemExit("Cannot configure the helper. Start the preview, then retry.") from None
        if status.tag == "error":
            raise SystemExit(status.text)
    print(status.findtext("summary"))
    print("Shared folders:")
    for item in status.findall("folders/folder"):
        print("  " + item.text)


if __name__ == "__main__":
    main()
