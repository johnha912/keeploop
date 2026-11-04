# Releasing keeploop

One tag publishes everything: `vX.Y.Z` on `main` uploads to PyPI, installs
the release back from PyPI to check it, then creates the GitHub release.
`.github/workflows/publish.yml` does all of it. No API token is stored
anywhere: PyPI trusts this repository's workflow through Trusted Publishing
(OIDC).

## Once: PyPI and TestPyPI setup (the repository owner, in a browser)

A phone browser works. GitHub cannot do these steps for you: they happen on
the PyPI websites.

- [ ] **PyPI account.** Register at <https://pypi.org/account/register/>,
      confirm the email, turn on two-factor authentication (an authenticator
      app is enough) and save the recovery codes.
- [ ] **TestPyPI account.** Same at <https://test.pypi.org/account/register/>.
      It is a separate site with separate accounts.
- [ ] **TestPyPI pending publisher.** <https://test.pypi.org/manage/account/publishing/>,
      "Add a new pending publisher", tab **GitHub**:

      | Field | Value |
      |---|---|
      | PyPI Project Name | `keeploop` |
      | Owner | `johnha912` |
      | Repository name | `keeploop` |
      | Workflow name | `publish.yml` |
      | Environment name | `testpypi` |

- [ ] **PyPI pending publisher.** <https://pypi.org/manage/account/publishing/>,
      the same fields, except **Environment name** `pypi`.
- [ ] **Optional, recommended: a human gate before the real upload.**
      GitHub repository, Settings, Environments, `pypi`, turn on
      *Required reviewers* and add yourself. Every release tag then waits
      for your click before it uploads to PyPI.

Every value must match exactly (`publish.yml`, not `publish.yaml`; `pypi`
in lower case). A mismatch fails the upload with "invalid-publisher".
A pending publisher does not reserve the name; the first successful upload
does, and the publisher then becomes a normal one for the project.

## Every release

1. Move the items under **Unreleased** in `CHANGELOG.md` into a new
   version section with today's date.
2. Set `__version__` in `prepare.py`, the only place the version lives
   (`setup.py` reads it), and the version badge in the three READMEs. A
   test checks both.
3. Run `python -m unittest discover -s tests` and
   `python tools/check_dist.py` (build, contents, clean-venv install,
   smoke test). Merge to `main` with CI green.
4. **Rehearse on TestPyPI.** Actions, publish, Run workflow on `main`. It
   uploads `X.Y.Z.devN` (N = run number, so a rehearsal never uses up a
   real version) and installs it back with pip and pipx on Linux and
   Windows.
5. **Tag once**, on the commit you rehearsed:

   ```bash
   git tag -a vX.Y.Z -m "keeploop X.Y.Z"
   git push origin vX.Y.Z
   ```

   No terminal at hand? On GitHub: Releases, *Draft a new release*, *Choose
   a tag*, type `vX.Y.Z`, *Create new tag on publish*, target `main`, leave
   the notes empty, *Publish release*. That pushes the same tag; the
   workflow fills in the release title and notes.

   The workflow refuses a tag that does not match `__version__`, runs the
   same gate, uploads to PyPI, installs the release back from PyPI with pip
   and pipx and smoke-tests it, and only then creates the GitHub release
   with the CHANGELOG section as its notes (`tools/release_notes.py`).
6. Open <https://pypi.org/project/keeploop/> and check the page: the
   README, its images and its links (they point at the tag).

PyPI never accepts the same version twice, even after a delete. If the
upload fails, fix the cause and re-run the failed job; if the release itself
is wrong, ship `X.Y.Z+1`.
