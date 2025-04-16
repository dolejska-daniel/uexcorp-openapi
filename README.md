# [UEX](https://uexcorp.space/) OpenAPI spec. generator

<img src="https://uexcorp.space/img/api/uex-api-badge-powered.png" width="150" alt="Powered by UEX" title="Powered by UEX">

### Purpose

This is an open-source tool designed to reverse-engineer OpenAPI spec for public APIs by intercepting traffic via `mitmproxy`, extracting request/response schemas, and generating accurate OpenAPI 3.0 specifications.
The aim is to improve accessibility and interoperability for developers working with these services.

### Components
`mitmproxy` is used to intercept HTTP(S) traffic from client applications.
`mitmproxy2swagger` automatically converts observed traffic into preliminary OpenAPI definitions.
Custom Python scripts post-process the output to merge fragments, correct inconsistencies, normalize paths, and enhance schema completeness.
