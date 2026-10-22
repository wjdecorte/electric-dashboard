# Wattwise

Wattwise is a local electricity dashboard for Synology Container Manager. Import Amicalola EMC PDFs, compare reported usage with last year, view cached weather by billing period, and record household events. SQLite stores statements, originals, events and settings on the NAS. No interval electricity readings or appliance usage are invented.

## Deployment pipeline

Push to **master** → GitHub Actions tests the application → builds Intel (`amd64`) and ARM (`arm64`) images → publishes to **ghcr.io/wjdecorte/electric-dashboard** → the NAS pulls and recreates project **electric**.

GitHub never connects to your NAS. No NAS credentials, inbound port forwarding or self-hosted runner are needed. GitHub Actions uses its automatically provided GITHUB_TOKEN with package-write permission; no publishing token must be added to repository secrets. Pull requests run tests without publishing.

Images are tagged `latest` for master, `sha-FULL_COMMIT_SHA` for every published build, and a version for `v*` release tags. A mutable latest tag makes routine upgrades easy; SHA tags support controlled rollouts.

## One-time NAS setup / migration

1. Wait for **Test and publish container** in GitHub Actions to complete.
2. In File Station, put `docker-compose.yml`, `update.sh`, and `scripts/prepare_data.py` in the existing NAS project folder, typically `/volume1/docker/electric-dashboard`. The scripts/ folder must be beside the Compose file.
3. **Keep your existing data/ folder.** Also retain old app/seed.json, app/account.json and app/location.json if present until the first migration completes. They are local initialization inputs; they never enter published images.
4. Check image access. New GHCR packages are private by default even for public repositories. Either log in to GHCR on the NAS, or change this code-only package to public in GitHub's package settings if anonymous pulls are desired. Do not expose the NAS dashboard itself to the internet.
5. Connect to the NAS over SSH and run:

```sh
cd /volume1/docker/electric-dashboard
sudo sh update.sh
```

Use your actual folder. The script defaults to Container Manager project **electric**. For a different name, use `sudo env PROJECT_NAME=your-project-name sh update.sh`.

If creating a new installation, create **Container Manager → Project → Create**, name it electric, choose this folder and the existing docker-compose.yml, then start it after registry access is configured. The published image starts empty: import the first PDF to establish the account, then choose the weather location in Settings. To use local private initialization files on a new installation, run update.sh before importing.

Visit **http://YOUR-NAS-IP:8088**. Web Station is optional. For a dedicated hostname or HTTPS, use a hostname-based portal/reverse proxy; path prefixes are not supported. Preserve the original Host header for API requests.

## Private registry login

For a private GHCR package, create a GitHub personal access token (classic) with **read:packages** and authorize it for the organization if required. Log in on the NAS using the same account that runs updates:

```sh
sudo docker login ghcr.io -u wjdecorte
```

At the password prompt, enter the token—not your GitHub password. Never put it in the Compose file, update.sh or a Git commit. A root-owned DSM task uses root's Docker credentials; logging in without sudo may not provide credentials to that task.

## Routine and optional automatic updates

Run `sudo sh update.sh` whenever you want the latest tested image. It:

- Pulls before stopping the running application; a download failure leaves it running.
- Skips recreation when the same image is already healthy.
- Tags the previous image for rollback.
- Stops the app, makes a consistent SQLite backup, and migrates local private initialization files into NAS storage only when needed.
- Recreates the existing electric project without building on the NAS.
- Checks container health and restores the previous image if startup fails.

Backups are kept under `data/backups/`, retaining the five most recent automatic snapshots. Automatic rollback restores the previous image, not the database; migrations currently add tables/fields without deleting old data. For a breaking migration, restore a matching database backup while the app is stopped. Initial installations without a previous image have no image rollback.

For hands-off updates, add **DSM Control Panel → Task Scheduler → Create → Scheduled Task → User-defined script**, run as root, and choose your preferred schedule (for example, nightly). Use:

```sh
sh /volume1/docker/electric-dashboard/update.sh
```

Enable failure notifications in DSM if desired. The task polls the registry; it requires outbound HTTPS only. The script prevents simultaneous updates with a lock folder. If a task is killed abruptly, check that no updater is running before removing stale `data/.update-lock`.

## Pinning / rollback

Copy .env.example to .env and set ELECTRIC_IMAGE to a published SHA tag:

```text
ELECTRIC_IMAGE=ghcr.io/wjdecorte/electric-dashboard:sha-FULL_COMMIT_SHA
```

Then run update.sh. The .env file is ignored by Git. Pinning holds that image until the setting is changed. To resume latest updates, set the image back to the latest tag.

For an immediate image rollback, temporarily set ELECTRIC_IMAGE=electric-dashboard:rollback in .env and use Container Manager to recreate/start the project with the existing local image. Do not delete data/. Do not remove the previous image until an upgrade is confirmed healthy.

## Storage and privacy

The `./data:/data` bind mount keeps runtime data outside containers. Retain this exact mapping and folder across upgrades. CSV/JSON downloads contain statement records, not household events or original attachments; back up the database for a complete copy.

Private seed/account/location JSON, uploaded PDFs, databases, exports and local secrets are ignored by Git. Published images also exclude private initialization JSON, data/, and Git metadata. A fresh GitHub clone starts without personal data. This local edition has no sign-in: limit its port to the home network/VPN.

## Weather and household events

Weather uses Open-Meteo historical reanalysis, a modeled regional record, not a sensor at the house. It is cached locally and remains usable offline. Requests send coordinates and dates, never statements or event notes. Settings allows a city or ZIP search; search sends that query to the geocoder. New weather needs outbound access to geocoding-api.open-meteo.com and archive-api.open-meteo.com.

Weather periods are start-inclusive/end-exclusive to avoid double-counting meter-reading boundaries. Heating/cooling degree days use a 65°F base. Missing days are marked incomplete; prior-year windows are marked approximate unless a matching prior-year statement establishes the dates. No weather-based appliance consumption or savings are inferred.

Household events support dated ranges, categories, notes, editing and deletion. They appear beside matching statements and as timeline markers. Initial extracted records may lack original attachments; imported new PDFs are retained.

## Local development

Production Compose only pulls a published image. To build locally:

```sh
docker compose -p electric-dev -f docker-compose.yml -f compose.local.yml up -d --build
```

Use a different folder/data mapping and port if running beside the NAS deployment. The same privacy exclusions apply to local images; private initialization JSON is not baked in. The NAS bootstrap script can migrate local inputs into data/.

Checks:

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
node --check app/static/app.js
node --check app/static/charts.js
```

## Troubleshooting

- **denied / unauthorized when pulling:** configure package access or log in using read:packages.
- **project looks stopped in Container Manager:** use PROJECT_NAME=electric, matching its UI project name exactly.
- **permission denied in data/:** allow container writes to the project data folder. Privileged mode is not required.
- **health check failed:** inspect `docker compose -p electric logs --tail 50`; update.sh restores the old image when available.
- **port already allocated:** edit the host side of `8088:8080` in the NAS Compose file.
- **nothing updates:** confirm the Actions run succeeded and check for a pinned ELECTRIC_IMAGE in .env.

References: [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry), [Docker multi-platform Actions](https://docs.docker.com/build/ci/github-actions/multi-platform/), [Synology projects](https://kb.synology.com/en-us/DSM/help/ContainerManager/docker_project?version=7).


### Weather comparison (2.1)

The weather section compares current and prior-year mean temperature, heating degree days and cooling degree days, with coverage counts and differences. Differences require complete coverage for both periods. A solid amber and dashed gray temperature series align by service-day number. Different billing lengths are retained.

If no prior-year electricity comparison is supplied, weather still uses the same calendar dates a year earlier (February 29 maps to February 28). Otherwise the existing matched or explicitly approximate billing window is used. New missing history is fetched at startup or with Refresh weather; cached weather remains usable offline.

## Add to iPhone home screen

Open the dashboard in Safari, tap Share, then Add to Home Screen. The Wattwise bolt icon and standalone full-screen mode come from `app/static/apple-touch-icon.png` and `manifest.webmanifest`.

---

Powered by DeCorte Industries, Inc. © 2026 DeCorte Industries, Inc.
