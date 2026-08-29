# CastFabric interface localization design

## Product language

The Chinese interface is the default and leads with the direct, conversational
slogan **“不挑协议，投了就播。”** The supporting sentence explains the product
without making the headline carry protocol details. The English counterpart is
**“Any protocol. Just press play.”** Both versions keep the existing calm,
editorial Dawn visual system.

## Language control

A compact language switch sits beside Settings in the top navigation. It shows
the alternative language (`EN` in Chinese, `中文` in English), has a localized
accessible label, and remains usable at the mobile breakpoint. The selected
locale is stored in `localStorage` under `castfabric.locale`. When no preference
exists, CastFabric defaults to Simplified Chinese instead of inferring a locale
from the operating system.

## Translation architecture

The single-file web UI keeps one dependency-free JavaScript dictionary with
`zh-CN` and `en` entries. Static elements use `data-i18n`,
`data-i18n-placeholder`, and `data-i18n-aria-label` attributes. Dynamic UI uses
the same `t(key, params)` function, including connection status, empty states,
save feedback, authentication, update progress, and device counts. Protocol
names, discovered device names, media metadata, version strings, and backend
error details remain data rather than translated copy.

Changing language updates the document `lang`, page title, static DOM, dynamic
status and current lists immediately without a page reload. Existing form state
is preserved. Interpolation escapes values before they enter HTML templates.

## Verification

- Parse all inline JavaScript and reject duplicate or missing DOM references.
- Assert every translation key exists in both locales.
- Run the full Python test suite and Docker package-data gate.
- Exercise Chinese and English at desktop and mobile viewport widths.
- Verify the language preference survives reload and that settings/modal state
  remains usable in both languages.
