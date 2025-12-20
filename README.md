---



\# UnityScraper



\*\*UnityScraper\*\* is a Python tool for downloading \*\*Xbox 360 Title Updates (TUs)\*\* and \*\*custom cover art\*\* directly from \*\*XboxUnity.net\*\*.



It supports:



\* CLI usage for automation and scripting

\* A simple Tkinter GUI for interactive use

\* Parallel downloads with rate limiting

\* Full archival of raw JSON metadata alongside downloaded files



This project is designed for \*\*local archiving, preservation, and tooling\*\*, not for live integration.



---



\## Features



\* ✅ Download \*\*Title Updates\*\* for one or more Xbox 360 TitleIDs

\* ✅ Download \*\*custom cover art\*\*

\* ✅ Saves \*\*raw JSON responses\*\* from XboxUnity for record-keeping

\* ✅ Parallel downloads (thread-safe)

\* ✅ Global rate limiting to avoid hammering the site

\* ✅ Automatic retries with backoff (including 429 handling)

\* ✅ Configurable output directory

\* ✅ CLI and GUI use the same backend logic



---



\## Requirements



\* Python \*\*3.9+\*\* recommended

\* Python packages:



&nbsp; ```bash

&nbsp; pip install requests

&nbsp; ```



Tkinter is included with standard Python installs on Windows.



---



\## Usage (CLI)



\### Basic usage



```bash

python main.py 555308C5,00000155

```



If you run without arguments, it will prompt:



```bash

python main.py

Enter TitleIDs separated by commas:

```



---



\### CLI Options



```bash

python main.py \[TITLEIDS] \[options]

```



| Option              | Description                                           |

| ------------------- | ----------------------------------------------------- |

| `TITLEIDS`          | Comma-separated TitleIDs (e.g. `555308C5,00000155`)   |

| `--out PATH`        | Output directory (default: `unityscrape`)             |

| `--workers N`       | Parallel workers per TitleID (default: 4)             |

| `--rate SECONDS`    | Minimum seconds between HTTP requests (default: 0.35) |

| `--log-level LEVEL` | DEBUG, INFO, WARNING, ERROR                           |



Example:



```bash

python main.py 555308C5 --out D:\\UnityArchive --workers 6 --rate 0.5

```



---



\## Usage (GUI)



Launch the GUI:



```bash

python GUI.py

```



\### GUI Features



\* Enter multiple TitleIDs

\* Choose output directory

\* Adjust:



&nbsp; \* Worker count

&nbsp; \* Request rate limit

\* Progress bar + live log output

\* Best-effort stop button



The GUI and CLI use the \*\*same scraping engine\*\*, so results are identical.



---



\## Output Structure



For each TitleID, files are saved under:



```

unityscrape/

└── TITLEID/

&nbsp;   ├── covers\_data.json

&nbsp;   ├── updates\_data.json

&nbsp;   ├── covers/

&nbsp;   │   ├── cover1.jpg

&nbsp;   │   └── cover2.png

&nbsp;   ├── MEDIAID1/

&nbsp;   │   └── updateversion3/

&nbsp;   │       └── tu\_file.bin

&nbsp;   └── MEDIAID2/

&nbsp;       └── updateversion5/

&nbsp;           └── tu\_file.bin

```



\### Notes



\* \*\*Raw JSON responses\*\* are always saved:



&nbsp; \* `covers\_data.json`

&nbsp; \* `updates\_data.json`

\* Title Updates are stored \*\*per MediaID and version\*\*

\* Existing files are overwritten if re-downloaded



---



\## TitleID Validation



\* TitleIDs must be \*\*8 hexadecimal characters\*\*

\* Invalid TitleIDs are skipped with a warning

\* All TitleIDs are normalized to \*\*uppercase\*\*



---



\## Networking Notes



\* ❗ \*\*HTTP ONLY\*\* — XboxUnity does \*\*not\*\* support HTTPS

\* Global rate limiting is enforced across all threads

\* Automatic retries with exponential backoff

\* Explicit handling for HTTP 429 (Too Many Requests)



---



\## Known Limitations



\* No authentication support (public endpoints only)

\* No resume for partially downloaded files

\* GUI stop button is \*\*best-effort\*\* (active downloads finish)



---



\## Intended Use



This project is intended for:



\* Offline archiving

\* Preservation

\* Research

\* Tooling / metadata collection



It is \*\*not\*\* intended for:



\* High-frequency scraping

\* Commercial redistribution

\* Bypassing site restrictions



Be respectful of XboxUnity’s infrastructure.



---



\## License



No explicit license is currently defined.

If you plan to redistribute or contribute, clarify licensing first.



---



\## Author



Created and maintained by \*\*Sthornberry9\*\*



---



If you want next steps, I’d recommend (in order):



1\. Adding a small `config.json` option

2\. Optional SQLite index for TitleIDs

3\. Resume support for large TU downloads

4\. Unit tests for JSON parsing



If you want any of those, say the word.



