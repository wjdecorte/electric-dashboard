---
name: Electric dashboard
description: Restrained light workspace for electricity evidence.
colors:
  bg: "#f4f6f8"
  surface: "#fff"
  ink: "#172b3a"
  muted: "#526273"
  line: "#dde4eb"
  blue: "#2457c5"
  prior: "#718096"
  weather: "#a85d12"
  success: "#18734b"
  error: "#b42318"
  soft: "#edf2fc"
typography:
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "32px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-.03em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "20px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-.02em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  metric:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "27px"
    fontWeight: 650
    lineHeight: 1.5
    letterSpacing: "-.02em"
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "normal"
rounded:
  field: "6px"
  button: "7px"
  surface: "12px"
spacing:
  compact: "8px"
  field-gap: "6px"
  control-gap: "10px"
  mobile-gutter: "16px"
  mobile-surface: "20px"
  section: "24px"
  desktop-gutter: "36px"
components:
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.surface}"
    rounded: "{rounded.button}"
    padding: "8px 13px"
    height: "38px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.button}"
    padding: "8px 13px"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "9px 10px"
  surface:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.surface}"
    padding: "24px"
---

# Design System: Electric dashboard

## Overview

A restrained light workspace makes statement evidence easy to inspect. Clear numbers, quiet surfaces and familiar controls support repeat use; blue usage, gray comparisons and amber weather preserve consistent meaning.

**Key Characteristics:** restrained light surfaces; evidence-first numbers; semantic chart colors.

## Colors

Primary blue marks current usage, active navigation and primary actions. Secondary amber identifies weather context. Neutral prior gray distinguishes comparison bars; ink and muted text establish hierarchy on white surfaces and a cool gray canvas. Line separates records; soft highlights selection. Success and error colors communicate feedback.

**The Series Meaning Rule.** Keep color meaning consistent across chart, legend and readout.

## Typography

The system sans-serif stack supports familiar, readable controls. Headline, title, body, metric and label roles are defined above. Numeric text uses tabular figures. Paragraphs stop at (74ch); labels remain sentence case. Phone headings reduce to (28px), with summary numbers at (25px).

## Layout

The page container tops out at (1440px), with desktop gutters of (36px) and section gaps of (24px). Navigation caps at (1368px). Summary metrics use four columns; analysis pairs a wide chart with a narrower context panel. At (1100px) analysis stacks. At (700px), gutters become (16px), surfaces use (20px) padding, summary becomes two columns and billing/forms stack. Chart history and tables retain horizontal scrolling.

## Elevation & Depth

Flat white surfaces sit on the cool gray canvas. No raised card shadows. Dividers and selection fills communicate grouping; active navigation uses a blue underline and selected chart periods an inset baseline.

## Shapes

Gently curved surfaces, tighter controls and subtle borders establish a practical workspace. Avoid ornamental silhouettes. Chart bars have softly rounded top corners; legends and event dots stay compact.

## Components

Primary buttons use blue with white text; secondary buttons use white and a light border. Hover backgrounds darken or tint, while focus uses a (3px) blue outline with (3px) offset. Fields use white, a distinct border and persistent labels. Navigation uses muted text with blue active text and underline. Surfaces group related evidence without elevation. Charts pair explicit legends, units and readouts; weather remains a separate line graph. Statement tables align numeric columns right. Empty, error and loading states use plain text and relevant actions. Reduced-motion users receive no button transition.

## Do's and Don'ts

- Do keep current usage blue, prior comparisons gray and weather amber.
- Do use tabular numbers, visible units and explicit missing-data states.
- Do keep keyboard focus visible and preserve chart scrolling on narrow screens.
- Don't introduce decorative raster imagery.
- Don't imply measured daily electricity or appliance causation through chart styling.
- Don't hide provenance or incomplete coverage behind visual polish.
