# Package Lab

Package Lab is UnityScraper's built-in Xbox package and image workspace. The
desktop page is available from the sidebar and the Tools menu.

## Supported Workflows

- **STFS (`CON`, `LIVE`, `PIRS`)**: inspect metadata, follow consecutive or
  fragmented file chains, inventory and extract files, verify data-block
  SHA-1 records, replace a file within its existing allocation, edit bounded
  public text metadata, and rebuild the hash tree.
- **Games on Demand / SVOD**: inspect a package header and adjacent `.data`
  directory, verify Data#### block hashes, and reconstruct the payload.
- **GDF/XISO**: inventory the directory tree and safely extract files from
  supported Xbox disc images.
- **FATX images**: discover known partitions, follow FATX16/FATX32 chains,
  inventory and extract files, and replace a file into a separate image when
  it fits the existing allocation.
- **GPD/XDBF**: inspect achievements, settings, title history, and images;
  update existing achievement or setting records into a separate output.

## Write Safety

Writes use a temporary file and atomic publication. FATX and GPD edits require
a separate output path. STFS replacement does not allocate new blocks: a
replacement must fit the file's existing chain. FATX replacement follows the
same rule. Source files remain unchanged when an operation fails.

STFS rehashing is available without signing. A caller can provide a signer
through the packages-domain callback interface; UnityScraper does not ship or
store private signing keys. The callback must return the signature bytes in
the package-specific representation expected by the caller's lawful signing
material.

## Deliberate Exclusions

UnityScraper does not bundle X360's embedded key resources, Le Fluffie's
updater or artwork, account credential modification, or DLC license bypasses.
It also does not write directly to a physical device. FATX work targets image
files, and destructive changes require an explicit output image.

## Attribution

Format geometry and field layouts were informed by Dalavin's GPLv3 X360
library and Le Fluffie lineage. UnityScraper uses a new Python implementation
with explicit bounds, transactional writes, and cross-platform paths. See
[Third-Party Notices](THIRD_PARTY_NOTICES.md).
