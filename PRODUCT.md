# Electric dashboard
<!-- impeccable:product-schema 1 -->

## Platform
web

## Stack
Python standard-library HTTP server, pdfplumber, SQLite, plain HTML/CSS/JavaScript. Docker on Synology Container Manager, project name electric.

## Users
A homeowner reviewing their own Amicalola EMC electricity statements on a home network.

## Product Purpose
Understand changes in statement-level electricity usage and charges, with prior-year comparisons, service-period weather and household events as context.

## Capabilities and Constraints
Original PDF import with validation, duplicate protection, same-account checks and original-file retention. Statement totals and daily averages only: the utility does not offer daily or hourly usage to the user. Weather is historical regional modeled data, cached locally; never represents appliance measurements. Household event ranges and notes can be created, edited and deleted. Current charges exclude prior balances and payments.

## Operating Context
NAS bind-mounted data folder, offline cached-weather access, manual rebuild/recreate update script. Local edition has no authentication and is intended for the home LAN/VPN. Private seed, account, location and runtime data stay out of Git. Fresh clones must start without private initialization files.

## Brand Commitments
User accepted the restrained light workspace, blue current usage, gray prior-year comparisons and amber weather theme recommended in chat.

## Evidence on Hand
14 initial real PDF statements with a gap in August 2025. Comparison values come from statement sections. Weather location configured privately from the user's ZIP; no location details are committed. No measured appliance or interval electricity data.

## Product Principles
Prefer daily averages for unequal service periods. Show provenance and incomplete coverage. Retain source records separately from computed weather summaries. Never infer appliance usage or savings from event annotations.
