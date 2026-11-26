# Preparing a release

Publication is separate from preparation. Do not move a published tag or
replace registry versions. Full releases align all Python distributions and
npm runtimes; a launcher-only patch has a separate version check.

## Prepare and validate

1. Update `pyjs.__version__`, workspace package versions and exact dependencies,
   both npm manifests, and `uv.lock`. Add `releases/VERSION.md` and move the
   changelog's pending entries into that version's section.
2. Run `python npm/scripts/release.py version --tag vVERSION`, the release
   tooling tests and normal PR CI. Review changes to the publishing workflow.
3. Build and install the Python artifacts locally:

   ```sh
   python scripts/check_distributions.py --out-dir dist/python-release
   python npm/scripts/release.py verify-python dist/python-release
   ```

   The output directory must be new. These are the exact wheels and source
   archives that passed isolated installation, not a subsequent rebuild.
4. Build and smoke-test a local npm runtime as described in
   [npm packaging](../npm/README.md). Other hosts require their native CI jobs.
5. After merging preparation, dispatch `publish.yml` with `target=all` on the
   intended commit. This runs the full CI and native-platform gates, then
   assembles `release-bundle` without publishing. Inspect its twelve archives,
   notes, revision and checksums. Artifacts expire after three days.

Single-target dispatch is only a packaging smoke test. It does not produce a
complete release or satisfy the full release gate.

## One-time publisher setup

Before pushing a release tag, configure required approvals and restrict tags
on the GitHub environments `npm`, `pypi` and `release`. Do not rely on an
environment name alone to enforce protection.

- Each PyPI project (`pyjs`, `pyjs-examples`, `pyjs-extras`) needs a trusted
  publisher for owner `pyjs`, repository `pyjs`, workflow `publish.yml`, and
  environment `pypi`.
- The six npm packages use the existing trusted publisher for `pyjs/pyjs`,
  `publish.yml`, environment `npm`.
- The `release` environment gates creation of the GitHub release and assets.

Use OIDC; do not add long-lived publishing tokens. PyPI setup is documented in
its [trusted publisher guide](https://docs.pypi.org/trusted-publishers/).

## Publish and verify

With explicit publication approval, tag the reviewed commit `vVERSION` and
push that tag. The workflow reruns both CI gates and publishes their retained
artifacts. It uploads Python distributions in dependency order, publishes npm
runtimes before the launcher, and creates the GitHub release after both
registries succeed. No publication job rebuilds a package.

Verify isolated registry installs and the GitHub assets against `SHA256SUMS`.
The workflow checks Linux registry installs; verify the other npm hosts using
their installation commands as part of release acceptance.

If a registry upload partially succeeds, stop and compare the existing files
and versions with the retained checksums before resuming. Do not blindly enable
skip-existing, overwrite GitHub assets, or rerun successful publish steps.
GitHub release creation deliberately fails if the release already exists;
inspect an uncertain network response before retrying. Repair publisher trust
instead of substituting a long-lived token. Expired build artifacts require
fresh validation of the same source revision before publication resumes.
