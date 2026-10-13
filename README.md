# Electric dashboard for Synology Container Manager

This package runs entirely on your NAS and includes the original 14 extracted statements. It has an Import statements button, PDF preview, duplicate detection, CSV/JSON exports and persistent storage. No cloud service is used to read PDFs.

## Install with Container Manager

1. Install **Container Manager** in DSM Package Center (on a supported NAS).
2. In File Station, create **docker/electric-dashboard**.
3. Upload and extract this ZIP into that folder. Ensure **docker-compose.yml**, **Dockerfile**, **requirements.txt**, **app/** and **data/** are directly inside it, not a second nested folder.
4. Open **Container Manager → Project → Create**.
5. Name the project **electric-dashboard**; set its path to the extracted folder.
6. Select **Use existing docker-compose.yml** (wording can vary by DSM version). Review the file and proceed to build and start the project. Web Station is not needed.
7. After the build completes, visit **http://YOUR-NAS-IP:8088** from your home network.

Initial build needs internet access to download the official Python image and PDF libraries. After that the dashboard and imports work locally. The image builds for the NAS architecture; no platform override is needed.

If port 8088 is already used, change the left side of `8088:8080` in docker-compose.yml, then run `sudo sh update.sh` from the project folder on the NAS. If DSM firewall is enabled, allow the chosen port from your local subnet.

## Import more statements

Select **Import statements**, choose one or several original Amicalola EMC PDFs, and review the extracted bill dates, kWh and charges. Select **Import N statements** to save the ready files.

- Original PDFs and extracted records are saved together in `data/statements.sqlite`.
- Existing statements are skipped; conflicting or overlapping billing periods are rejected.
- Only statements matching the original utility account can be imported.
- Meter differences, service days and charge totals must reconcile.
- Maximum 10 MB and 5 pages per PDF. Password-protected PDFs, scans without text, and changed/unsupported layouts are rejected with an explanation. No appliance-level usage is inferred.
- Imported originals have a **Download original PDF** link. The initial 14 records contain extracted data only; keep your original PDFs separately.
- Any newly discovered billing years appear in the Period menu automatically.

## Storage, backups and updates

The `./data:/data` bind mount stores the database on the NAS outside the container. Restarting, rebuilding or recreating the container preserves it as long as you retain this folder and mapping. Do not delete or replace `data/` when updating application files.

For a consistent backup, stop this project, copy the **data** folder using File Station or your NAS backup tool, then restart it. Restore while stopped by placing the saved data folder back before starting. CSV/JSON exports contain extracted records, not the original PDF attachments.

To update the application, stop the project, replace app/, Dockerfile and requirements.txt, keep data/, then connect to the NAS over SSH and run `sudo sh update.sh` from this project folder. This explicitly builds a fresh image and recreates the container. If your Container Manager project has a different name, use `sudo env PROJECT_NAME=your-project-name sh update.sh`.

## Access

This local edition has no sign-in and serves PDFs to anyone who can access its port. Keep it on your home LAN; do not forward this port to the internet. For remote access, use your VPN or an authenticated reverse proxy. The original ChatGPT-hosted version is separate and is not updated by NAS imports.

## Troubleshooting

- **Build fails:** inspect Project/container logs; check NAS internet access and free disk space.
- **Database is read-only / permission denied:** ensure the project's data folder permits writes by the container. The supplied container uses Docker's default user and does not require privileged mode.
- **Can't connect:** verify the project is running and healthy, the NAS IP is correct, the host port is free and DSM firewall permits LAN access.
- **Statement rejected:** use the original downloadable PDF; check that it is the same account and layout. A bill with new charge labels needs an importer update.

Optional command-line deployment from the project folder: `docker compose up -d --build`.

References:
- Synology projects: https://kb.synology.com/en-us/DSM/help/ContainerManager/docker_project?version=7
- Docker persistent storage: https://docs.docker.com/engine/storage/bind-mounts/

## Prior-year comparison bars

Total kWh and kWh-per-day views show blue current-period bars alongside brown bars for **Same period last year**, taken from the statement Comparisons section. A missing/zero reported prior-year value is labeled N/A. Daily comparisons use the prior-year period's own service days. No prior-year cost is plotted because it is not reported in these statements.

On existing installations, this version automatically fills comparison service days for the 14 initial statements. New imports also capture those days. To apply this update, keep your existing data/ folder, replace app/ with the updated app/ folder, and rebuild/start the Container Manager project.


## When the GUI only restarts the container

A restart does not rebuild code copied into the image. After copying the updated app/ files to the NAS project folder, connect over SSH and run:

```sh
cd /volume1/docker/electric-dashboard
sudo sh update.sh
```

Use your actual NAS volume/folder and the exact Container Manager project name. The default project name is electric-dashboard. For another name:

```sh
sudo env PROJECT_NAME=your-project-name sh update.sh
```

The script stops on a failed build, leaving the running container in place. It does not delete or replace data/. Successful output includes Docker build steps and a container recreation, not just a restart. Refresh the dashboard afterward.
